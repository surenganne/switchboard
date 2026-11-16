import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_scan import build_fixture, skill, write

ROOT = Path(__file__).resolve().parent.parent
FIX = json.loads((ROOT / "tests/fixtures/review_profiles.json").read_text())
ROUTE_TOOL = "mcp__plugin_switchboard_switchboard__route"


class HooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sb = self.root / "sbhome"
        self.env = dict(os.environ, SWITCHBOARD_HOME=str(self.sb), SWITCHBOARD_CLAUDE_HOME=str(self.root / "empty"),
                        CLAUDE_PROJECT_DIR=str(self.root / "noproj"))
        os.environ["SWITCHBOARD_HOME"] = str(self.sb)

    def tearDown(self):
        os.environ.pop("SWITCHBOARD_HOME", None)
        self.tmp.cleanup()

    def run_hook(self, script, stdin):
        p = subprocess.run([sys.executable, str(ROOT / "switchboard" / script)], input=stdin, text=True,
                           capture_output=True, env=self.env, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def session(self):
        return self.run_hook("hook_session.py", json.dumps({"session_id": "s1", "hook_event_name": "SessionStart", "source": "startup"}))

    def pretool(self, tool, inp=None, sid="s1"):
        out = self.run_hook("hook_pretool.py", json.dumps({"session_id": sid, "tool_name": tool, "tool_input": inp or {}}))
        return json.loads(out) if out.strip() else None

    def seed_review_profiles(self):
        """A fake ~/.claude holding the fixture's review skills, with the fixture profiles saved against it."""
        from switchboard import profiles, scan_claude
        ch = self.root / "rc"
        write(ch / "skills/review/SKILL.md", skill("review", "Pre-landing review"))
        installed, enabled = {}, {}
        for plugin, names in (("ecc", ("code-review", "review-pr", "orch-review")), ("ponytail", ("ponytail-review",))):
            for n in names:
                write(self.root / "p" / plugin / "skills" / n / "SKILL.md", skill(n, f"{plugin} {n}"))
            installed[f"{plugin}@m"] = [{"scope": "user", "installPath": str(self.root / "p" / plugin)}]
            enabled[f"{plugin}@m"] = True
        write(ch / "plugins/installed_plugins.json", json.dumps({"plugins": installed}))
        write(ch / "settings.json", json.dumps({"enabledPlugins": enabled}))
        self.env["SWITCHBOARD_CLAUDE_HOME"] = str(ch)
        inv = {s["id"]: s for s in scan_claude.list_skills(ch, None)}
        for sid, p in FIX["profiles"].items():
            if sid in inv:
                self.assertEqual(profiles.save(dict(p, content_hash=inv[sid]["content_hash"]), inv), [])

    def deny(self, out):
        return out is not None and out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_session_silent_when_nothing_to_say(self):
        self.assertEqual(self.session(), "")
        self.assertTrue((self.sb / "inventory.json").exists())

    def test_session_lists_overlap_and_pending(self):
        from switchboard import profiles
        ch, proj = build_fixture(self.root)
        self.env.update(SWITCHBOARD_CLAUDE_HOME=str(ch), CLAUDE_PROJECT_DIR=str(proj))
        self.session()  # writes inventory
        inv = json.loads((self.sb / "inventory.json").read_text())["skills"]
        for sid in ("user:alpha", "plug:beta"):
            p = {"id": sid, "source": inv[sid]["source"], "content_hash": inv[sid]["content_hash"],
                 "categories": ["code-review"], "does": "x", "targets": ["pr"], "focus": [], "depth": "quick",
                 "cost": "single-pass", "stack": ["any"], "best_for": [], "not_for": []}
            self.assertEqual(profiles.save(p, inv), [])
        out = json.loads(self.session())["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        msg = out["additionalContext"]
        self.assertIn("code-review", msg)
        self.assertIn("route", msg)
        self.assertIn("2 skills or agents are new or changed since profiling", msg)

    def test_session_offers_profiling_only_when_pending_set_changes(self):
        ch, proj = build_fixture(self.root)
        self.env.update(SWITCHBOARD_CLAUDE_HOME=str(ch), CLAUDE_PROJECT_DIR=str(proj))
        self.assertIn("4 skills or agents are new or changed since profiling", self.session())
        self.assertEqual(self.session(), "")  # same pending set: say nothing again
        write(ch / "skills/epsilon/SKILL.md", skill("epsilon", "New skill"))
        self.assertIn("5 skills or agents are new or changed since profiling", self.session())

    def test_profiling_offer_is_remembered_per_project(self):
        ch, proj = build_fixture(self.root)
        other = self.root / "proj2"
        write(other / ".claude/skills/omega/SKILL.md", skill("omega", "Other project skill"))
        self.env["SWITCHBOARD_CLAUDE_HOME"] = str(ch)
        for p in (proj, other):
            self.env["CLAUDE_PROJECT_DIR"] = str(p)
            self.assertIn("new or changed since profiling", self.session())
        for p in (proj, other):  # switching back and forth: nothing new, so no repeat offer
            self.env["CLAUDE_PROJECT_DIR"] = str(p)
            self.assertEqual(self.session(), "")

    def test_pretool_denies_unrouted_overlap_skill_at_most_twice(self):
        self.seed_review_profiles()
        out = self.pretool("Skill", {"skill": "ecc:code-review"})
        self.assertTrue(self.deny(out))
        self.assertIn("route", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "ecc:code-review"})))
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))  # capped: never stuck

    def test_pretool_cap_is_per_session_not_per_skill(self):
        self.seed_review_profiles()
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "ecc:code-review"})))
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "review"})))  # another overlapping skill
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:review-pr"}))  # same window, cap reached
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "review"}, sid="s2")))  # user skills by bare name

    def prompt(self, text, sid="s1"):
        return self.run_hook("hook_prompt.py", json.dumps({"session_id": sid, "hook_event_name": "UserPromptSubmit",
                                                           "prompt": text}))

    def test_pretool_never_blocks_a_skill_the_user_named(self):
        self.seed_review_profiles()
        self.assertEqual(self.prompt("please run /ecc:code-review on this and /review after"), "")  # adds no context
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        self.assertIsNone(self.pretool("Skill", {"skill": "review"}))
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "ecc:review-pr"})))  # not named: still routed
        state = json.loads(next((self.sb / "state").glob("*.json")).read_text())
        self.assertNotIn("please", json.dumps(state))  # names only, never prompt text

    def usage_ids(self):
        log = self.sb / "usage.jsonl"
        return [json.loads(l)["id"] for l in log.read_text().splitlines()] if log.exists() else []

    def fixture_session(self):
        ch, proj = build_fixture(self.root)
        self.env.update(SWITCHBOARD_CLAUDE_HOME=str(ch), CLAUDE_PROJECT_DIR=str(proj))
        self.session()
        return json.loads((self.sb / "inventory.json").read_text())["skills"]

    def test_session_notes_first_seen(self):
        inv = self.fixture_session()
        self.assertEqual(set(json.loads((self.sb / "first_seen.json").read_text())), set(inv))

    def test_pretool_logs_skill_call(self):
        self.fixture_session()
        self.pretool("Skill", {"skill": "alpha"})
        self.assertEqual(self.usage_ids(), ["user:alpha"])
        self.prompt("use /alpha please")  # named by the user: allowed through, still logged
        self.pretool("Skill", {"skill": "alpha"})
        self.assertEqual(self.usage_ids(), ["user:alpha", "user:alpha", "user:alpha"])

    def test_pretool_drops_unknown(self):
        self.fixture_session()
        self.pretool("Skill", {"skill": "not-installed"})
        self.assertEqual(self.usage_ids(), [])

    def test_session_with_recording_off_restarts_window(self):
        self.fixture_session()
        self.assertTrue((self.sb / "first_seen.json").exists())
        (self.sb / "settings.json").write_text(json.dumps({"record_usage": False}))
        self.session()
        self.assertFalse((self.sb / "first_seen.json").exists())

    def test_usage_falls_back_to_live_scan(self):
        self.fixture_session()
        # another project's session start overwrote the shared inventory
        (self.sb / "inventory.json").write_text(json.dumps({"version": 1, "skills": {}}))
        self.pretool("Skill", {"skill": "delta"})
        self.prompt("try /alpha")
        ids = self.usage_ids()
        self.assertEqual(len(ids), 2)
        self.assertTrue(ids[0].startswith("project:") and ids[0].endswith(":delta"))
        self.assertEqual(ids[1], "user:alpha")

    def test_prompt_logs_named(self):
        self.fixture_session()
        self.prompt("run /alpha on src/x and /Users/me/file")
        self.assertEqual(self.usage_ids(), ["user:alpha"])

    def test_prompt_hook_survives_bad_input(self):
        self.assertEqual(self.prompt(""), "")
        self.assertEqual(self.run_hook("hook_prompt.py", "not json"), "")

    def test_pretool_asks_for_a_choice_after_route_and_allows_after_record(self):
        self.seed_review_profiles()
        self.assertIsNone(self.pretool(ROUTE_TOOL, {"task": {"category": "code-review"}}))
        out = self.pretool("Skill", {"skill": "ecc:code-review"})
        self.assertTrue(self.deny(out))
        self.assertIn("record_choice", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("AskUserQuestion", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.pretool(ROUTE_TOOL.replace("__route", "__record_choice"), {"chosen": "ecc:code-review"}))
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        self.assertIsNone(self.pretool("Skill", {"skill": "review"}))  # a recorded choice covers the window
        self.assertIsNotNone(self.pretool("Skill", {"skill": "ecc:code-review"}, sid="s2"))  # another session has not chosen

    def reminder(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else None

    def test_prompt_reminds_to_route_overlap_work_until_a_choice(self):
        self.seed_review_profiles()
        self.assertIsNone(self.reminder(self.prompt("what time is it")))  # no task area
        msg = self.reminder(self.prompt("can you look over my diff before I open a pull request"))
        self.assertIn("code-review", msg)
        self.assertIn("AskUserQuestion", msg)
        # an ignored reminder must not silence the next prompt
        self.assertIsNotNone(self.reminder(self.prompt("now review the tests too")))
        self.pretool(ROUTE_TOOL.replace("__route", "__record_choice"), {"chosen": "ecc:code-review"})
        self.assertIsNone(self.reminder(self.prompt("review the rest")))  # quiet after a choice
        for f in (self.sb / "state").glob("*.json"):
            self.assertNotIn("diff", f.read_text())  # prompt text is never stored

    def test_prompt_no_reminder_after_choice_or_named_skill_or_without_overlap(self):
        self.seed_review_profiles()
        self.assertIsNone(self.reminder(self.prompt("review this with /ecc:code-review")))
        self.assertIsNone(self.reminder(self.prompt("deploy it to kubernetes", sid="s3")))  # no overlap in that area
        self.pretool(ROUTE_TOOL.replace("__route", "__record_choice"), {"chosen": "ecc:code-review"}, sid="s2")
        self.assertIsNone(self.reminder(self.prompt("review my diff", sid="s2")))

    def test_prompt_areas_cover_everyday_task_wording(self):
        from switchboard import hook_prompt
        areas = lambda p: {a for a, rx in hook_prompt.AREA_RE.items() if rx.search(p)}
        for p, want in [("fix the tie-breaking in route.py", "debugging"),
                        ("why does the hook not fire?", "debugging"),
                        ("I don't see any routing recommendations", "debugging"),
                        ("analyze the router flow and find the issue", "code-review"),
                        ("refactor scan_claude.py to be simpler", "code-review"),
                        ("This plugin has to be generic. check this", "code-review"),
                        ("implement user-level commands scanning", "planning"),
                        ("add a feature to export the report as PDF", "planning")]:
            self.assertIn(want, areas(p), p)
        for p in ("thanks", "what time is it", "sounds good"):
            self.assertEqual(areas(p), set(), p)

    def test_prompt_ignores_closing_tags(self):
        self.prompt("<summary>x</summary> <task-id>1</task-id> run /cso")
        state = json.loads(next((self.sb / "state").glob("*.json")).read_text())
        self.assertEqual(state["named"], ["cso"])

    def test_hooks_json_matches_record_choice(self):
        hooks = json.loads((Path(__file__).parent.parent / "hooks/hooks.json").read_text())
        self.assertIn(ROUTE_TOOL.replace("__route", "__record_choice"), hooks["hooks"]["PreToolUse"][0]["matcher"])

    def test_pretool_logs_agent_calls_and_never_blocks_them(self):
        from switchboard import profiles, scan_claude
        self.seed_review_profiles()
        write(self.root / "p/ecc/agents/code-reviewer.md", "---\nname: code-reviewer\ndescription: Reviews code\n---\nx\n")
        inv = {s["id"]: s for s in scan_claude.list_skills(self.root / "rc", None)}
        p = dict(FIX["profiles"]["ecc:code-review"], id="ecc:code-reviewer", cost="multi-agent",
                 content_hash=inv["ecc:code-reviewer"]["content_hash"])
        self.assertEqual(profiles.save(p, inv), [])  # an overlapping code-review agent
        for _ in range(3):  # a skill's workflow may start the same agent repeatedly: never denied
            self.assertIsNone(self.pretool("Agent", {"subagent_type": "ecc:code-reviewer", "prompt": "x"}))
        self.assertIsNone(self.pretool("Task", {"subagent_type": "ecc:code-reviewer"}))  # older tool name
        self.pretool("Agent", {"subagent_type": "general-purpose"})  # built-in agent: not installed, not logged
        self.pretool("Skill", {"skill": "ecc:code-reviewer"})  # a Skill call never resolves to an agent
        self.assertEqual(self.usage_ids(), ["ecc:code-reviewer"] * 4)
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "ecc:code-review"})))  # skills still routed
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text())
        self.assertTrue({"Agent", "Task", "Skill"} <= set(hooks["hooks"]["PreToolUse"][0]["matcher"].split("|")))

    def test_pretool_allows_non_overlap_skill(self):
        self.seed_review_profiles()
        self.assertIsNone(self.pretool("Skill", {"skill": "some:unprofiled"}))
        self.assertIsNone(self.pretool("Bash", {"command": "ls"}))

    def test_pretool_uses_live_scan_not_shared_inventory_file(self):
        self.seed_review_profiles()
        # another session in another project overwrote the shared inventory
        (self.sb / "inventory.json").write_text(json.dumps({"version": 1, "skills": {}}))
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "ecc:code-review"})))

    def test_pretool_ignores_uninstalled_skill(self):
        self.seed_review_profiles()
        import shutil
        shutil.rmtree(self.root / "p/ecc/skills/review-pr")
        shutil.rmtree(self.root / "p/ecc/skills/orch-review")
        shutil.rmtree(self.root / "p/ecc/skills/code-review")
        shutil.rmtree(self.root / "rc/skills/review")
        self.assertIsNone(self.pretool("Skill", {"skill": "ponytail:ponytail-review"}))  # only one left: no overlap

    def test_pretool_fails_open_on_garbage_stdin_and_corrupt_state(self):
        self.seed_review_profiles()
        self.assertEqual(self.run_hook("hook_pretool.py", "not json"), "")
        self.run_hook("hook_session.py", "not json")  # reads no stdin; must still exit 0
        (self.sb / "state").mkdir(exist_ok=True)
        (self.sb / "state/s1.json").write_text("{oops")
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        (self.sb / "state/s3.json").write_text("[1, 2]")
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}, sid="s3"))

    def test_pretool_session_id_cannot_escape_state_dir(self):
        self.seed_review_profiles()
        self.pretool("Skill", {"skill": "ecc:code-review"}, sid="../../evil")
        self.assertFalse((self.root / "evil.json").exists())
        self.assertFalse((self.sb.parent / "evil.json").exists())

    def test_old_state_files_are_deleted(self):
        self.seed_review_profiles()
        (self.sb / "state").mkdir(exist_ok=True)
        old = self.sb / "state/old.json"
        old.write_text("{}")
        t = time.time() - 2 * 86400
        os.utime(old, (t, t))
        self.pretool("Bash", {})
        self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()

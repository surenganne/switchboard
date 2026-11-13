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
        self.assertIn("2 skills are not profiled yet", msg)

    def test_session_offers_profiling_only_when_pending_set_changes(self):
        ch, proj = build_fixture(self.root)
        self.env.update(SWITCHBOARD_CLAUDE_HOME=str(ch), CLAUDE_PROJECT_DIR=str(proj))
        self.assertIn("4 skills are not profiled yet", self.session())
        self.assertEqual(self.session(), "")  # same pending set: say nothing again
        write(ch / "skills/epsilon/SKILL.md", skill("epsilon", "New skill"))
        self.assertIn("5 skills are not profiled yet", self.session())

    def test_profiling_offer_is_remembered_per_project(self):
        ch, proj = build_fixture(self.root)
        other = self.root / "proj2"
        write(other / ".claude/skills/omega/SKILL.md", skill("omega", "Other project skill"))
        self.env["SWITCHBOARD_CLAUDE_HOME"] = str(ch)
        for p in (proj, other):
            self.env["CLAUDE_PROJECT_DIR"] = str(p)
            self.assertIn("not profiled yet", self.session())
        for p in (proj, other):  # switching back and forth: nothing new, so no repeat offer
            self.env["CLAUDE_PROJECT_DIR"] = str(p)
            self.assertEqual(self.session(), "")

    def test_pretool_denies_unrouted_overlap_skill_once(self):
        self.seed_review_profiles()
        out = self.pretool("Skill", {"skill": "ecc:code-review"})
        self.assertTrue(self.deny(out))
        self.assertIn("route", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))

    def test_pretool_blocks_once_per_session_not_per_skill(self):
        self.seed_review_profiles()
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "ecc:code-review"})))
        self.assertIsNone(self.pretool("Skill", {"skill": "review"}))  # another overlapping skill, same window
        self.assertTrue(self.deny(self.pretool("Skill", {"skill": "review"}, sid="s2")))  # user skills by bare name

    def test_pretool_allows_after_route(self):
        self.seed_review_profiles()
        self.assertIsNone(self.pretool(ROUTE_TOOL, {"task": {"category": "code-review"}}))
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        self.assertIsNotNone(self.pretool("Skill", {"skill": "ecc:code-review"}, sid="s2"))  # another session has not routed

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

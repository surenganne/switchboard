import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_scan import build_fixture

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
        from switchboard import paths, profiles
        paths.write_private(paths.home() / "inventory.json", json.dumps({"version": 1, "skills": FIX["inventory"]}))
        for p in FIX["profiles"].values():
            self.assertEqual(profiles.save(p, FIX["inventory"]), [])

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

    def test_pretool_denies_unrouted_overlap_skill_once(self):
        self.seed_review_profiles()
        out = self.pretool("Skill", {"skill": "ecc:code-review"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("route", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        # user skills are invoked by bare name
        self.assertEqual(self.pretool("Skill", {"skill": "review"})["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_pretool_allows_after_route(self):
        self.seed_review_profiles()
        self.assertIsNone(self.pretool(ROUTE_TOOL, {"task": {"category": "code-review"}}))
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        # another session has not routed
        self.assertIsNotNone(self.pretool("Skill", {"skill": "ecc:code-review"}, sid="s2"))

    def test_pretool_allows_non_overlap_skill(self):
        self.seed_review_profiles()
        self.assertIsNone(self.pretool("Skill", {"skill": "some:unprofiled"}))
        self.assertIsNone(self.pretool("Bash", {"command": "ls"}))

    def test_pretool_fails_open_on_garbage_stdin_and_corrupt_state(self):
        self.seed_review_profiles()
        self.assertEqual(self.run_hook("hook_pretool.py", "not json"), "")
        self.assertEqual(self.run_hook("hook_session.py", "not json"), "")
        (self.sb / "state").mkdir(exist_ok=True)
        (self.sb / "state/s1.json").write_text("{oops")
        self.assertIsNone(self.pretool("Skill", {"skill": "ecc:code-review"}))
        (self.sb / "inventory.json").write_text("{oops")
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

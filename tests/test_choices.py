import json
import os
import tempfile
import unittest
from pathlib import Path

from switchboard import choices

TASK = {"category": "code-review", "targets": ["pr"], "focus": ["security"], "stack": ["python"],
        "depth": "standard", "summary": "review my secret payments diff"}


class ChoicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SWITCHBOARD_HOME"] = self.tmp.name
        self.log = Path(self.tmp.name) / "choices.jsonl"

    def tearDown(self):
        os.environ.pop("SWITCHBOARD_HOME", None)
        self.tmp.cleanup()

    def lines(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def test_record_drops_summary(self):
        choices.record(TASK, ["a:x", "b:y"], "b:y")
        (row,) = self.lines()
        self.assertEqual(set(row), {"date", "category", "targets", "focus", "stack", "depth", "cost", "offered", "chosen"})
        self.assertNotIn("payments", self.log.read_text())
        self.assertEqual(row["chosen"], "b:y")
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_record_keeps_only_schema_values(self):
        # free text smuggled into feature fields is dropped, so no prompt text is stored
        choices.record(dict(TASK, targets=["pr", "fix the auth bug in login.py"], depth="very deep"), ["a:x"], "a:x")
        (row,) = self.lines()
        self.assertEqual(row["targets"], ["pr"])
        self.assertIsNone(row["depth"])

    def test_record_keeps_only_known_skill_ids(self):
        choices.record(TASK, ["a:x", "please fix the bug in payments.py"], "my secret prompt text", known={"a:x", "b:y"})
        (row,) = self.lines()
        self.assertEqual((row["offered"], row["chosen"]), (["a:x"], None))

    def test_record_respects_off_setting(self):
        (Path(self.tmp.name) / "settings.json").write_text(json.dumps({"record_choices": False}))
        choices.record(TASK, ["a:x"], "a:x")
        self.assertFalse(self.log.exists())

    def test_similar_matches_by_features(self):
        choices.record(TASK, ["a:x", "b:y"], "b:y")
        choices.record(dict(TASK, targets=["files"], focus=["bloat"]), ["a:x"], "a:x")
        choices.record(dict(TASK, category="docs"), ["a:x"], "a:x")
        got = choices.similar({"category": "code-review", "targets": ["pr", "local-diff"], "focus": ["security"]})
        self.assertEqual([c["chosen"] for c in got], ["b:y"])  # Jaccard 2/3 >= 0.5

    def test_audit_flags_repeated_overrides(self):
        choices.record(TASK, ["a:x", "b:y"], "b:y")
        choices.record(TASK, ["a:x", "b:y"], "b:y")
        choices.record(dict(TASK, focus=["bloat"]), ["a:x", "b:y"], "b:y")  # only once: not flagged
        choices.record(TASK, ["a:x", "b:y"], "a:x")
        (g,) = choices.audit()
        self.assertEqual((g["category"], g["targets"], g["focus"], g["overrides"]), ("code-review", ["pr"], ["security"], 2))

    def test_audit_survives_dropped_choice(self):
        choices.record(TASK, ["a:x", "b:y"], "b:y", known={"a:x", "b:y"})
        choices.record(TASK, ["a:x", "b:y"], "gone:skill", known={"a:x", "b:y"})  # stored as chosen null
        choices.record(TASK, ["a:x", "b:y"], "b:y", known={"a:x", "b:y"})
        (g,) = choices.audit()
        self.assertEqual((g["overrides"], g["chosen"]), (2, ["b:y"]))

    def test_forget_clears(self):
        choices.record(TASK, ["a:x"], "a:x")
        choices.record(TASK, ["a:x"], "a:x")
        self.assertEqual(choices.forget(), 2)
        self.assertFalse(self.log.exists())
        self.assertEqual(choices.forget(), 0)
        self.assertEqual(choices.similar(TASK), [])


if __name__ == "__main__":
    unittest.main()

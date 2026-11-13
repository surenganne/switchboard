import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from switchboard import usage

INV = {"user:review": {}, "ecc:code-review": {}, "project:ab12cd34:deploy": {}}


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SWITCHBOARD_HOME"] = self.tmp.name
        self.home = Path(self.tmp.name)
        self.log = self.home / "usage.jsonl"

    def tearDown(self):
        os.environ.pop("SWITCHBOARD_HOME", None)
        self.tmp.cleanup()

    def test_record_row_shape(self):
        usage.record(["user:a"], today="2026-11-13")
        self.assertEqual([json.loads(l) for l in self.log.read_text().splitlines()], [{"date": "2026-11-13", "id": "user:a"}])
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)

    def test_record_off(self):
        (self.home / "settings.json").write_text(json.dumps({"record_usage": False}))
        usage.record(["user:a"])
        self.assertFalse(self.log.exists())
        self.assertFalse(usage.recording_on())

    def test_resolve(self):
        self.assertEqual(usage.resolve("ecc:code-review", INV), "ecc:code-review")
        self.assertEqual(usage.resolve("review", INV), "user:review")
        self.assertEqual(usage.resolve("deploy", INV), "project:ab12cd34:deploy")
        self.assertIsNone(usage.resolve("nope", INV))
        self.assertIsNone(usage.resolve("Users", INV))

    def test_note_seen_keeps_first_date(self):
        usage.note_seen(["a"], "2026-11-01")
        usage.note_seen(["a", "b"], "2026-11-13")
        self.assertEqual(usage.first_seen(), {"a": "2026-11-01", "b": "2026-11-13"})

    def test_corrupt_files(self):
        self.log.write_text('{"date": "2026-11-13", "id": "user:a"}\nnot json\n{"id": "no-date"}\n')
        self.assertEqual(usage.rows(), [{"date": "2026-11-13", "id": "user:a"}])
        (self.home / "first_seen.json").write_text("[]")
        self.assertEqual(usage.first_seen(), {})

    def test_forget_deletes_both(self):
        usage.record(["user:a"], today="2026-11-13")
        usage.note_seen(["user:a"], "2026-11-13")
        self.assertEqual(usage.forget(), 1)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.home / "first_seen.json").exists())


if __name__ == "__main__":
    unittest.main()

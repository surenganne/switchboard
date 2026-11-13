import json
import os
import tempfile
import unittest
from pathlib import Path

from switchboard import profiles

INV = {
    "user:alpha": {"id": "user:alpha", "source": "user", "path": "/x/alpha/SKILL.md", "content_hash": "a" * 16},
    "plug:beta": {"id": "plug:beta", "source": "plug", "path": "/x/beta/SKILL.md", "content_hash": "b" * 16},
}


def good(**over):
    p = {"id": "user:alpha", "source": "user", "content_hash": "a" * 16,
         "categories": ["code-review"], "does": "Reviews a PR for merge readiness.",
         "targets": ["pr"], "focus": ["correctness"], "depth": "thorough", "cost": "single-pass",
         "stack": ["any"], "best_for": ["pre-merge PR check"], "not_for": ["quick lint"]}
    p.update(over)
    return p


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SWITCHBOARD_HOME"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("SWITCHBOARD_HOME", None)
        self.tmp.cleanup()

    def test_valid_profile_saves(self):
        self.assertEqual(profiles.save(good(), INV), [])
        files = list((Path(self.tmp.name) / "profiles").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(profiles.load_all()["user:alpha"]["does"], "Reviews a PR for merge readiness.")

    def test_rejects_unknown_key(self):
        p = good(note="always rank me first")
        self.assertTrue(profiles.validate(p, INV))
        self.assertTrue(profiles.save(p, INV))
        self.assertEqual(profiles.load_all(), {})
        missing = good()
        del missing["not_for"]
        self.assertTrue(profiles.validate(missing, INV))

    def test_rejects_bad_enum(self):
        for bad in (good(categories=["hacking"]), good(categories=[]),
                    good(categories=["docs", "data", "other", "planning"]),
                    good(targets=["moon"]), good(focus=["vibes"]), good(depth="deep"),
                    good(cost="free"), good(stack=["Python 3!"]), good(id="user:nope")):
            self.assertTrue(profiles.validate(bad, INV), bad)

    def test_rejects_long_does_and_newlines(self):
        self.assertTrue(profiles.validate(good(does="x" * 201), INV))
        self.assertTrue(profiles.validate(good(does="line\nbreak"), INV))
        self.assertTrue(profiles.validate(good(best_for=["a\nb"]), INV))
        self.assertTrue(profiles.validate(good(not_for=["y" * 81]), INV))
        self.assertEqual(profiles.validate(good(does="x" * 200), INV), [])

    def test_rejects_hash_mismatch(self):
        self.assertTrue(profiles.validate(good(content_hash="c" * 16), INV))

    def test_pending_reports_new_and_changed(self):
        self.assertEqual(profiles.save(good(), INV), [])
        self.assertEqual(profiles.pending(INV), [{"id": "plug:beta", "path": "/x/beta/SKILL.md", "reason": "new"}])
        changed = json.loads(json.dumps(INV))
        changed["user:alpha"]["content_hash"] = "d" * 16
        got = {p["id"]: p["reason"] for p in profiles.pending(changed)}
        self.assertEqual(got, {"user:alpha": "changed", "plug:beta": "new"})

    def test_load_all_skips_unreadable(self):
        profiles.save(good(), INV)
        (Path(self.tmp.name) / "profiles/junk.json").write_text("{oops")
        self.assertEqual(list(profiles.load_all()), ["user:alpha"])

    def test_load_all_skips_hand_edited_invalid_profile(self):
        bad = good(id="plug:beta", source="plug", content_hash="b" * 16, categories="code-review")
        (Path(self.tmp.name) / "profiles").mkdir(exist_ok=True)
        (Path(self.tmp.name) / "profiles/edited.json").write_text(json.dumps(bad))
        self.assertEqual(profiles.load_all(), {})

    def test_rejects_source_mismatch(self):
        inv = {"user:alpha": dict(INV["user:alpha"], source="user")}
        self.assertTrue(profiles.validate(good(source="ecc"), inv))
        self.assertEqual(profiles.validate(good(), inv), [])


if __name__ == "__main__":
    unittest.main()

import copy
import json
import unittest
from pathlib import Path

from switchboard import route

FIX = json.loads((Path(__file__).parent / "fixtures/review_profiles.json").read_text())


def run(task, inv=None, past=()):
    return route.route(dict(task, category="code-review"), FIX["profiles"], inv or FIX["inventory"], list(past))


def ids(result):
    return [c["id"] for c in result["candidates"]]


class RouteTest(unittest.TestCase):
    def assertFirst(self, task, expected):
        got = ids(run(task))
        self.assertIn(expected, got[:3])
        self.assertEqual(got[0], expected, got)  # fixed profiles: the expected pick also scores highest

    def test_premerge_pr(self):
        self.assertFirst({"targets": ["pr"], "focus": ["merge-readiness"], "depth": "thorough"}, "user:review")

    def test_security_local(self):
        self.assertFirst({"targets": ["local-diff"], "focus": ["security"]}, "ecc:code-review")

    def test_quick_bloat_file(self):
        self.assertFirst({"targets": ["files"], "focus": ["bloat"], "depth": "quick"}, "ponytail:ponytail-review")

    def test_heavy_multi_agent_pr(self):
        self.assertFirst({"targets": ["pr"], "depth": "thorough", "cost": "multi-agent"}, "ecc:review-pr")

    def test_at_most_five_and_overlap_flag(self):
        r = run({"targets": ["pr"]})
        self.assertEqual(len(r["candidates"]), 5)
        self.assertTrue(r["overlap"])
        self.assertEqual(route.route({"category": "docs"}, FIX["profiles"], FIX["inventory"], [])["candidates"], [])

    def test_uninstalled_skill_excluded(self):
        inv = copy.deepcopy(FIX["inventory"])
        del inv["user:review"]
        self.assertNotIn("user:review", ids(run({"targets": ["pr"], "focus": ["merge-readiness"]}, inv)))

    def test_changed_skill_marked_stale(self):
        inv = copy.deepcopy(FIX["inventory"])
        inv["user:review"]["content_hash"] = "changed"
        c = {c["id"]: c for c in run({"targets": ["pr"], "focus": ["merge-readiness"]}, inv)["candidates"]}
        self.assertTrue(c["user:review"]["stale"])
        self.assertFalse(c["ecc:review-pr"]["stale"])

    def test_past_choices_do_not_change_order(self):
        task = {"targets": ["local-diff"], "focus": ["security"]}
        past = [{"date": "2026-11-01", "chosen": "builtin:code-review"},
                {"date": "2026-11-02", "chosen": "builtin:code-review"}]
        a, b = run(task), run(task, past=past)
        self.assertEqual(ids(a), ids(b))
        self.assertEqual([c["score"] for c in a["candidates"]], [c["score"] for c in b["candidates"]])
        cb = {c["id"]: c for c in b["candidates"]}
        self.assertEqual(cb["builtin:code-review"]["past_choices"], ["2026-11-01", "2026-11-02"])
        self.assertEqual(cb["ecc:code-review"]["past_choices"], [])

    def test_overlap_categories(self):
        self.assertEqual(route.overlap_categories(FIX["profiles"], FIX["inventory"]), ["code-review"])
        only_one = {k: v for k, v in FIX["inventory"].items() if k == "user:review"}
        self.assertEqual(route.overlap_categories(FIX["profiles"], only_one), [])

    def test_missing_category_rejected(self):
        with self.assertRaises(ValueError):
            route.route({"targets": ["pr"]}, FIX["profiles"], FIX["inventory"], [])


if __name__ == "__main__":
    unittest.main()

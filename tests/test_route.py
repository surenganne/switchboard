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

    def test_tag_stuffed_profile_does_not_outrank_precise_skill(self):
        profs = copy.deepcopy(FIX["profiles"])
        inv = copy.deepcopy(FIX["inventory"])
        stuffed = dict(profs["builtin:code-review"], id="aaa:all", targets=["pr", "local-diff", "files", "repo", "url", "design"],
                       focus=["security", "correctness", "bloat", "performance", "merge-readiness", "tests"])
        profs["aaa:all"], inv["aaa:all"] = stuffed, dict(inv["builtin:code-review"], id="aaa:all")
        for task, want in (({"targets": ["local-diff"], "focus": ["security"]}, "ecc:code-review"),
                           ({"targets": ["pr"], "focus": ["merge-readiness"], "depth": "thorough"}, "user:review"),
                           ({"targets": ["files"], "focus": ["bloat"], "depth": "quick"}, "ponytail:ponytail-review")):
            got = [c["id"] for c in route.route(dict(task, category="code-review"), profs, inv, [])["candidates"]]
            self.assertEqual(got[0], want, (task, got))

    def test_full_task_match_outranks_narrow_partial_match(self):
        # real case: a "respond to review comments" helper (one target, one focus) beat /review on a PR review
        base = dict(FIX["profiles"]["builtin:code-review"], depth="standard", cost="single-pass", stack=["any"])
        profs = {"aaa:narrow": dict(base, id="aaa:narrow", targets=["pr"], focus=["correctness"]),
                 "zzz:broad": dict(base, id="zzz:broad", targets=["pr", "local-diff"],
                                   focus=["correctness", "security", "merge-readiness", "tests"])}
        inv = {sid: dict(FIX["inventory"]["builtin:code-review"], id=sid) for sid in profs}
        task = {"category": "code-review", "targets": ["pr"], "focus": ["correctness", "merge-readiness"]}
        got = [c["id"] for c in route.route(task, profs, inv, [])["candidates"]]
        self.assertEqual(got, ["zzz:broad", "aaa:narrow"])

    def test_roles_match_profile_schema(self):
        from switchboard import profiles
        self.assertEqual(route.ROLES, profiles.ROLES)

    def test_matching_role_ranks_first_then_unknown_then_other(self):
        base = dict(FIX["profiles"]["builtin:code-review"], depth="standard", cost="single-pass", stack=["any"],
                    targets=["pr"], focus=["merge-readiness"])
        profs = {"a:helper": dict(base, id="a:helper", role="assists"),  # best tag match, wrong role
                 "b:legacy": dict(base, id="b:legacy", focus=["style"]),  # no role yet
                 "c:reviewer": dict(base, id="c:reviewer", focus=["style"], role="performs")}
        inv = {sid: dict(FIX["inventory"]["builtin:code-review"], id=sid) for sid in profs}
        task = {"category": "code-review", "targets": ["pr"], "focus": ["merge-readiness"]}
        ranked = lambda t: [c["id"] for c in route.route(t, profs, inv, [])["candidates"]]
        self.assertEqual(ranked(task), ["c:reviewer", "b:legacy", "a:helper"])  # tasks default to performs
        self.assertEqual(ranked(dict(task, role="assists")), ["a:helper", "b:legacy", "c:reviewer"])

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

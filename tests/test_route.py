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

    def test_limit_overlap_flag_and_next_step(self):
        r = run({"targets": ["pr"]})
        self.assertEqual(len(r["candidates"]), min(len(FIX["profiles"]), route.LIMIT))
        self.assertTrue(r["overlap"])
        self.assertIn("AskUserQuestion", r["next"])
        self.assertIn("record_choice", r["next"])
        empty = route.route({"category": "docs"}, FIX["profiles"], FIX["inventory"], [])
        self.assertEqual(empty["candidates"], [])
        self.assertNotIn("next", empty)

    def test_candidates_say_how_to_invoke_them(self):
        inv = copy.deepcopy(FIX["inventory"])
        inv["ecc:review-pr"].update(kind="agent", name="review-pr")  # pretend this one is a plugin agent
        got = {c["id"]: (c["kind"], c["invoke"]) for c in run({"targets": ["pr"]}, inv)["candidates"]}
        self.assertEqual(got["ecc:review-pr"], ("agent", {"tool": "Agent", "subagent_type": "ecc:review-pr"}))
        self.assertEqual(got["user:review"], ("skill", {"tool": "Skill", "skill": "review"}))
        self.assertEqual(got["ecc:code-review"][1], {"tool": "Skill", "skill": "ecc:code-review"})
        self.assertEqual(route.invoke({"source": "project:ab12cd34", "name": "x", "kind": "agent"}),
                         {"tool": "Agent", "subagent_type": "x"})

    def test_skill_for_another_language_ranks_below_any_stack(self):
        profs = copy.deepcopy(FIX["profiles"])
        profs["ecc:orch-review"].update(stack=["kotlin"], focus=["correctness", "security"], depth="thorough")
        task = {"category": "code-review", "targets": ["pr"], "focus": ["correctness", "security"], "depth": "thorough"}
        for stack, last in ((None, True), (["python"], True), (["kotlin"], False)):
            got = ids(route.route(dict(task, stack=stack) if stack else task, profs, FIX["inventory"], []))
            self.assertEqual(got[-1] == "ecc:orch-review", last, (stack, got))

    def test_past_choice_breaks_ties_only(self):
        task = {"targets": ["local-diff"], "focus": ["correctness"]}
        a = run(task)["candidates"]
        tied = next(t for t in ([c["id"] for c in a if c["score"] == x["score"]] for x in a) if len(t) > 1)  # equal scores only
        b = ids(run(task, past=[{"date": "2026-11-01", "chosen": tied[-1]}]))
        self.assertLess(b.index(tied[-1]), b.index(tied[0]))  # the picked one moves ahead within its tie
        best = a[0]["id"]
        self.assertEqual(ids(run(task, past=[{"date": "2026-11-01", "chosen": a[-1]["id"]}] * 5))[0], best)

    def test_lighter_skill_wins_a_tie_when_task_names_no_cost(self):
        base = {"categories": ["testing"], "targets": ["repo"], "focus": ["tests"], "role": "performs", "stack": ["any"]}
        profs = {"a:workflow": dict(base, cost="workflow", targets=["repo"]),  # more precise, but heavier
                 "z:light": dict(base, cost="single-pass", targets=["repo", "local-diff"])}
        inv = {k: {} for k in profs}
        got = route.route({"category": "testing", "targets": ["repo"]}, profs, inv, [])["candidates"]
        self.assertEqual([c["id"] for c in got], ["z:light", "a:workflow"])
        self.assertEqual(got[0]["score"], got[1]["score"])
        asked = route.route({"category": "testing", "targets": ["repo"], "cost": "workflow"}, profs, inv, [])
        self.assertEqual(asked["candidates"][0]["id"], "a:workflow")  # a stated cost still wins on score

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
        self.assertNotIn("stale", c["ecc:review-pr"])  # only set when true, to keep the result small

    def test_past_choices_do_not_change_order(self):
        task = {"targets": ["local-diff"], "focus": ["security"]}
        past = [{"date": "2026-11-01", "chosen": "builtin:code-review"},
                {"date": "2026-11-02", "chosen": "builtin:code-review"}]
        a, b = run(task), run(task, past=past)
        self.assertEqual(ids(a), ids(b))
        self.assertEqual([c["score"] for c in a["candidates"]], [c["score"] for c in b["candidates"]])
        cb = {c["id"]: c for c in b["candidates"]}
        self.assertEqual(cb["builtin:code-review"]["past_choices"], 2)  # times picked for similar tasks
        self.assertNotIn("past_choices", cb["ecc:code-review"])

    def test_result_fits_under_context_tool_cutoff(self):
        profs = copy.deepcopy(FIX["profiles"])
        inv = copy.deepcopy(FIX["inventory"])
        for n in range(20):  # many overlapping, wordy profiles
            sid = f"bulk:r{n}"
            inv[sid] = dict(inv["user:review"], id=sid, source="bulk", name=f"r{n}")
            profs[sid] = dict(profs["user:review"], id=sid, source="bulk", does="d" * 200,
                              best_for=["b" * 80] * 5, not_for=["n" * 80] * 5)
        r = route.route({"category": "code-review", "targets": ["pr"]}, profs, inv, [])
        self.assertLessEqual(len(json.dumps(r)), route.MAX_BYTES)
        self.assertGreaterEqual(len(r["candidates"]), route.MIN_KEEP)
        for c in r["candidates"]:
            self.assertLessEqual(set(c), {"id", "kind", "invoke", "score", "does", "best_for", "not_for", "role", "cost",
                                          "stale", "past_choices"})
        self.assertNotIn("content_hash", json.dumps(r))  # the rest of the profile stays local
        # still over the cap at MIN_KEEP: text fields are shed, the candidates stay
        old, route.MAX_BYTES = route.MAX_BYTES, 900
        try:
            r = route.route({"category": "code-review", "targets": ["pr"]}, profs, inv, [])
        finally:
            route.MAX_BYTES = old
        self.assertLessEqual(len(json.dumps(r)), 900)
        self.assertEqual(len(r["candidates"]), route.MIN_KEEP)
        self.assertTrue(all("not_for" not in c and "invoke" in c for c in r["candidates"]))

    def test_overlap_categories(self):
        self.assertEqual(route.overlap_categories(FIX["profiles"], FIX["inventory"]), ["code-review"])
        only_one = {k: v for k, v in FIX["inventory"].items() if k == "user:review"}
        self.assertEqual(route.overlap_categories(FIX["profiles"], only_one), [])

    def test_missing_category_rejected(self):
        with self.assertRaises(ValueError):
            route.route({"targets": ["pr"]}, FIX["profiles"], FIX["inventory"], [])


if __name__ == "__main__":
    unittest.main()

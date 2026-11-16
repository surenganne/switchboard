import base64
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from switchboard import report

INV = {
    "user:review": {"id": "user:review", "source": "user", "content_hash": "h1"},
    "ecc:code-review": {"id": "ecc:code-review", "source": "ecc", "content_hash": "h2"},
    "ecc:plan": {"id": "ecc:plan", "source": "ecc", "content_hash": "h3"},
}
PROFS = {"user:review": {"id": "user:review", "content_hash": "h1", "categories": ["code-review"]},
         "ecc:code-review": {"id": "ecc:code-review", "content_hash": "OLD", "categories": ["code-review", "security"]},
         "gone:skill": {"id": "gone:skill", "content_hash": "x", "categories": ["docs"]}}


def row(date, chosen, offered=("user:review", "ecc:code-review"), category="code-review"):
    return {"date": date, "category": category, "targets": ["pr"], "focus": [], "stack": [], "depth": None,
            "cost": None, "offered": list(offered), "chosen": chosen}


ROWS = [row("2026-11-02", "user:review"), row("2026-11-03", "ecc:code-review"),
        row("2026-11-10", "ecc:code-review"), row("2026-11-11", None), {"junk": True}]


class ReportTest(unittest.TestCase):
    def test_summary_numbers(self):
        s = report.summarise(INV, PROFS, ROWS)
        self.assertEqual((s["skills"], s["profiled"], s["stale"]), (3, 2, 1))  # gone:skill is not installed
        self.assertEqual(s["picks"], 3)  # null choice and junk rows ignored
        self.assertEqual(s["overrides"], 2)
        self.assertEqual(s["top_skills"][0], ("ecc:code-review", 2, 3))  # chosen 2 of 3 times offered
        self.assertEqual(s["by_source"], [("ecc", 2, 1, 2, 0, 0), ("user", 1, 1, 1, 0, 0)])  # + skills, commands, agents
        self.assertEqual(s["weeks"], [("2026-W45", 2), ("2026-W46", 1)])
        self.assertEqual(s["by_category"], [("code-review", 3, 2)])

    def test_profiled_skills_table(self):
        s = report.summarise(INV, PROFS, ROWS)
        self.assertEqual(s["profiled_skills"], [("ecc:code-review", "code-review, security", "", 2, 3, True, "skill"),
                                                ("user:review", "code-review", "", 1, 3, False, "skill")])
        page = report.render(s)
        self.assertIn("Profiled skills (2)", page)
        self.assertIn("ecc:code-review *", page)  # stale marker

    def test_weeks_fill_gaps_between_first_and_last(self):
        s = report.summarise(INV, PROFS, [row("2026-10-01", "user:review"), row("2026-10-20", "user:review")])
        self.assertEqual(s["weeks"], [("2026-W40", 1), ("2026-W41", 0), ("2026-W42", 0), ("2026-W43", 1)])

    def test_html_escapes_untrusted_text_and_loads_nothing_external(self):
        bad = "x:<script>alert(1)</script>"
        inv = dict(INV, **{bad: {"id": bad, "source": "<b>x", "content_hash": "h"}})
        page = report.render(report.summarise(inv, PROFS, ROWS + [row("2026-11-12", bad, offered=(bad,))]))
        self.assertEqual(page.lower().count("<script"), 1)  # only the bundled sticker player
        self.assertIn("&lt;script&gt;", page)
        self.assertNotRegex(page, r"(?i)(src|href|url)\s*[=(]\s*[\"']?(https?:)?//")

    def test_sticker_script_is_pinned_by_csp(self):
        page = report.render(report.summarise(INV, PROFS, ROWS))
        script = re.search(r"<script>(.*)</script>", page, re.S).group(1)
        self.assertNotIn("</script", script.lower())
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)
        self.assertIn("default-src 'none'", csp)
        self.assertIn(f"script-src 'sha256-{digest}'", csp)
        for name in re.findall(r'data-sticker="([^"]+)"', page):
            self.assertIn(name, ("folder", "search", "pin", "toggle", "calendar", "trophy", "mailbox", "play", "chat", "coins", "bulb"))

    def test_usage_cost_and_kind_sections(self):
        from datetime import date
        inv = {
            "user:review": {"id": "user:review", "name": "review", "source": "user", "kind": "skill", "desc_chars": 36},
            "ecc:code-review": {"id": "ecc:code-review", "name": "code-review", "source": "ecc", "kind": "command",
                                "plugin_key": "ecc@ecc", "desc_chars": 76},
            "ecc:code-reviewer": {"id": "ecc:code-reviewer", "name": "code-reviewer", "source": "ecc", "kind": "agent",
                                  "plugin_key": "ecc@ecc", "desc_chars": 36},
        }
        picks = [row("2026-11-02", "ecc:code-reviewer", offered=("ecc:code-reviewer", "user:review")),
                 row("2026-11-03", "user:review", offered=("ecc:code-reviewer", "user:review")),
                 row("2026-11-10", "user:review", offered=("user:review", "ecc:code-review"))]  # no agent offered
        uses = [{"date": "2026-11-02", "id": "ecc:code-reviewer"}, {"date": "2026-11-04", "id": "user:review"},
                {"date": "2026-11-04", "id": "user:review"}, {"date": "2026-09-01", "id": "ecc:code-review"},
                {"date": "2026-11-05", "id": "gone:old"}, {"bad": 1}]
        s = report.summarise(inv, {}, picks, uses, {"ecc@ecc": ["chrome-devtools"]}, today=date(2026, 11, 16))
        self.assertEqual(s["kinds"], {"skill": 1, "command": 1, "agent": 1})
        self.assertEqual(s["by_kind"], [("skill", 1, 0), ("command", 1, 0), ("agent", 1, 0)])
        self.assertEqual((s["uses"], s["uses_recent"]), (5, 4))  # the bad row dropped; September is outside 30 days
        self.assertEqual(s["top_used"][0], ("user:review", "skill", 2))
        self.assertIn(("gone:old", "removed", 1), s["top_used"])
        self.assertEqual(s["picks_run"], 2)  # run the same day (11-02) or the next (11-03 → 11-04); 11-10 never ran
        ecc = next(x for x in s["by_plugin"] if x[0] == "ecc@ecc")
        self.assertEqual(ecc, ("ecc@ecc", 0, 1, 1, ecc[4], 1, 2, "chrome-devtools"))  # one of two used in 30 days
        self.assertEqual(s["tokens"], sum(x[4] for x in s["by_plugin"]))
        self.assertEqual(s["agent_vs_skill"], [("code-review", 2, 1, 1)])  # only picks offering both kinds
        page = report.render(s)
        for text in ("Actual usage", "Most run", "Context cost by plugin", "chrome-devtools", "Agents vs skills",
                     "1 skills · 1 commands · 1 agents", "2 of 3 picks"):
            self.assertIn(text, page)

    def test_profiling_notice(self):
        s = report.summarise(INV, PROFS, ROWS)  # ecc:plan has no profile; ecc:code-review is stale
        self.assertEqual((s["unprofiled"], s["stale"]), ({"skill": 1}, 1))
        page = report.render(s)
        self.assertIn("Profiling needed", page)
        self.assertIn("1 have no profile yet (1 skill) and 1 changed since they were profiled", page)
        self.assertIn("/switchboard:profile", page)
        done = {sid: dict(p, content_hash=INV[sid]["content_hash"]) for sid, p in PROFS.items() if sid in INV}
        done["ecc:plan"] = {"id": "ecc:plan", "content_hash": "h3", "categories": ["planning"]}
        self.assertIn("All 3 entries are profiled and up to date", report.render(report.summarise(INV, done, ROWS)))

    def test_usage_off_and_empty(self):
        s = report.summarise(INV, PROFS, ROWS, [{"date": "2026-11-02", "id": "user:review"}], recording=False)
        self.assertIn("Usage logging is off", report.render(s))
        self.assertIn("No runs logged yet", report.render(report.summarise(INV, PROFS, ROWS)))
        self.assertNotIn("Agents vs skills", report.render(report.summarise(INV, PROFS, ROWS)))  # no mixed picks

    def test_empty_data_renders(self):
        page = report.render(report.summarise({}, {}, []))
        self.assertIn("No picks yet", page)

    def test_write_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SWITCHBOARD_HOME"] = tmp
            try:
                Path(tmp, "choices.jsonl").write_text(json.dumps(row("2026-11-02", "user:review")) + "\n")
                out = report.write(INV, PROFS)
                self.assertEqual(out, Path(tmp) / "report.html")
                self.assertEqual(out.stat().st_mode & 0o777, 0o600)
                self.assertIn("user:review", out.read_text())
            finally:
                os.environ.pop("SWITCHBOARD_HOME")


if __name__ == "__main__":
    unittest.main()

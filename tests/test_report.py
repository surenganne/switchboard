import json
import os
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
        self.assertEqual(s["by_source"], [("ecc", 2, 1), ("user", 1, 1)])
        self.assertEqual(s["weeks"], [("2026-W45", 2), ("2026-W46", 1)])
        self.assertEqual(s["by_category"], [("code-review", 3, 2)])

    def test_profiled_skills_table(self):
        s = report.summarise(INV, PROFS, ROWS)
        self.assertEqual(s["profiled_skills"], [("ecc:code-review", "code-review, security", "", 2, 3, True),
                                                ("user:review", "code-review", "", 1, 3, False)])
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
        self.assertNotIn("<script", page.lower())
        self.assertIn("&lt;script&gt;", page)
        self.assertNotRegex(page, r"(?i)(src|href|url)\s*[=(]\s*[\"']?(https?:)?//")

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

import unittest

from switchboard import hygiene

TODAY = "2026-12-20"


def rec(sid, plugin_key=None, desc_chars=40):
    source, name = sid.rsplit(":", 1)
    r = {"id": sid, "name": name, "source": source.split(":")[0], "path": f"/x/{name}/SKILL.md", "desc_chars": desc_chars}
    if plugin_key:
        r["plugin_key"] = plugin_key
    return r


def build():
    inv = {}
    for sid in ("p:one", "p:two"):
        inv[sid] = rec(sid, "p@m")
    for n in range(1, 7):
        inv[f"q:s{n}"] = rec(f"q:s{n}", "q@m")
    for sid in ("user:a", "user:new"):
        inv[sid] = rec(sid)
    inv["switchboard:status"] = rec("switchboard:status", "switchboard@switchboard")
    seen = {sid: "2026-11-01" for sid in inv}
    seen["user:new"] = "2026-12-17"
    rows = [{"date": "2026-12-10", "id": "q:s1"}]
    return inv, rows, seen


class HygieneTest(unittest.TestCase):
    def test_tokens_formula(self):
        self.assertEqual(hygiene.tokens({"name": "abc", "desc_chars": 12}), 14)
        self.assertEqual(hygiene.tokens({"name": "abc", "desc_chars": 13}), 15)
        self.assertEqual(hygiene.tokens({"name": "abc", "description": "x" * 12}), 14)

    def test_collecting(self):
        inv, rows, _ = build()
        out = hygiene.suggest(inv, rows, {sid: "2026-12-01" for sid in inv}, TODAY)
        self.assertEqual(out, {"collecting": True, "days_logged": 19, "window_days": 30})
        self.assertEqual(hygiene.suggest(inv, rows, {}, TODAY)["days_logged"], 0)

    def test_recording_off(self):
        inv, rows, seen = build()
        self.assertEqual(hygiene.suggest(inv, rows, seen, TODAY, recording=False), {"recording": False})

    def test_unused_plugin_and_skill(self):
        out = hygiene.suggest(*build(), TODAY)
        self.assertFalse(out["collecting"])
        self.assertEqual([(p["plugin_key"], p["skills"]) for p in out["plugins"]], [("p@m", 2)])
        self.assertEqual([s["id"] for s in out["skills"]], ["user:a"])
        self.assertEqual(out["skills"][0]["path"], "/x/a/SKILL.md")
        listed = [p["plugin_key"] for p in out["plugins"] + out["mostly_unused"]] + [s["id"] for s in out["skills"]]
        self.assertFalse(any("switchboard" in x for x in listed))

    def test_mostly_unused(self):
        out = hygiene.suggest(*build(), TODAY)
        (q,) = out["mostly_unused"]
        self.assertEqual((q["plugin_key"], q["used"], q["skills"]), ("q@m", ["q:s1"], 6))
        self.assertEqual(q["tokens"], sum(hygiene.tokens(r) for sid, r in build()[0].items() if sid.startswith("q:")))

    def test_window_edge(self):
        inv, rows, seen = build()
        out = hygiene.suggest(inv, rows + [{"date": "2026-11-20", "id": "user:a"}], seen, TODAY)
        self.assertEqual(out["skills"], [])

    def test_uninstalled_rows_ignored(self):
        inv, rows, seen = build()
        self.assertEqual(hygiene.suggest(inv, rows + [{"date": TODAY, "id": "gone:x"}], seen, TODAY),
                         hygiene.suggest(inv, rows, seen, TODAY))

    def test_tokens_after(self):
        inv = build()[0]
        out = hygiene.suggest(*build(), TODAY)
        self.assertEqual(out["tokens_now"], sum(hygiene.tokens(r) for r in inv.values()))
        self.assertEqual(out["tokens_after"], out["tokens_now"] - sum(p["tokens"] for p in out["plugins"])
                         - sum(s["tokens"] for s in out["skills"]))

    def test_days_clamped(self):
        inv, rows, seen = build()
        self.assertEqual(hygiene.suggest(inv, rows, seen, TODAY, days=1)["window_days"], 7)
        self.assertEqual(hygiene.suggest(inv, rows, seen, TODAY, days="x")["window_days"], 30)


if __name__ == "__main__":
    unittest.main()

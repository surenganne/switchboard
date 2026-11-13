import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_scan import build_fixture

SERVER = Path(__file__).resolve().parent.parent / "switchboard" / "mcp_server.py"


class McpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        ch, proj = build_fixture(root)
        env = dict(os.environ, SWITCHBOARD_HOME=str(root / "sbhome"), SWITCHBOARD_CLAUDE_HOME=str(ch),
                   CLAUDE_PROJECT_DIR=str(proj))
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, env=env, cwd="/")
        self.n = 0

    def tearDown(self):
        self.proc.stdin.close()
        self.proc.wait(5)
        self.proc.stdout.close()
        self.tmp.cleanup()

    def send_raw(self, line):
        self.proc.stdin.write(line)
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def rpc(self, method, params=None):
        self.n += 1
        return self.send_raw(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")

    def call(self, name, **args):
        res = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return res["isError"], json.loads(res["content"][0]["text"])

    def test_initialize_and_list_tools(self):
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(init["result"]["serverInfo"]["name"], "switchboard")
        # notifications get no reply: the next line read must be the ping's
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.assertIn("result", self.rpc("ping"))
        tools = {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(tools, {"route", "record_choice", "pending_profiles", "save_profile", "pending_roles", "set_role",
                                 "status", "audit", "forget", "report", "hygiene"})

    def test_hygiene_collecting(self):
        err, out = self.call("hygiene")
        self.assertFalse(err)
        self.assertEqual(out, {"collecting": True, "days_logged": 0, "window_days": 30})
        self.assertEqual(self.call("status")[1]["hygiene"], "collecting 0/30")

    def test_role_backfill_roundtrip(self):
        err, pend = self.call("pending_profiles", limit=20)
        alpha = next(p for p in pend["pending"] if p["id"] == "user:alpha")
        prof = {"id": "user:alpha", "source": alpha["source"], "content_hash": alpha["content_hash"],
                "categories": ["code-review"], "does": "Reviews things.", "targets": ["pr"], "focus": [],
                "depth": "standard", "cost": "single-pass", "stack": ["any"], "best_for": [], "not_for": []}
        self.assertTrue(self.call("save_profile", profile=prof)[1]["saved"])
        self.assertEqual(self.call("status")[1]["missing_role"], 1)
        err, roles = self.call("pending_roles", limit=10)
        self.assertEqual([(r["id"], r["name"], r["description"]) for r in roles["pending"]],
                         [("user:alpha", "alpha", "User skill alpha")])
        self.assertEqual(roles["pending"][0]["content_hash"], alpha["content_hash"])
        err, ok = self.call("set_role", id="user:alpha", content_hash=alpha["content_hash"], role="performs")
        self.assertEqual(ok, {"saved": True, "errors": []})
        self.assertEqual(self.call("status")[1]["missing_role"], 0)

    def test_save_then_route_roundtrip(self):
        err, pend = self.call("pending_profiles", limit=20)
        self.assertFalse(err)
        self.assertEqual(pend["total"], 4)
        alpha = next(p for p in pend["pending"] if p["id"] == "user:alpha")
        prof = {"id": "user:alpha", "source": alpha["source"], "content_hash": alpha["content_hash"],
                "categories": ["code-review"], "does": "Reviews things.", "targets": ["pr"], "focus": ["correctness"],
                "depth": "standard", "cost": "single-pass", "stack": ["any"], "best_for": [], "not_for": []}
        err, saved = self.call("save_profile", profile=prof)
        self.assertEqual(saved, {"saved": True, "errors": []})
        err, bad = self.call("save_profile", profile=dict(prof, depth="deep"))
        self.assertFalse(bad["saved"])
        err, r = self.call("route", task={"category": "code-review", "targets": ["pr"], "summary": "x"})
        self.assertEqual([c["id"] for c in r["candidates"]], ["user:alpha"])
        self.assertFalse(r["overlap"])
        err, st = self.call("status")
        self.assertEqual((st["skills"], st["profiled"], st["pending"]), (4, 1, 3))
        self.assertFalse(self.call("record_choice", task={"category": "code-review", "targets": ["pr"]},
                                   offered=["user:alpha"], chosen="user:alpha")[0])
        err, rep = self.call("report")
        self.assertFalse(err)
        self.assertTrue(rep["path"].endswith("report.html"))
        self.assertEqual((rep["picks"], rep["skills"]), (1, 4))
        err, refused = self.call("forget")  # deleting needs an explicit confirm
        self.assertEqual((refused["removed"], refused["error"][:8]), (0, "confirm:"))
        self.assertEqual(self.call("forget", confirm=True)[1], {"removed": 1, "usage_removed": 0})

    def test_record_choice_resolves_bare_name_and_rejects_unknown(self):
        log = Path(self.tmp.name) / "sbhome" / "choices.jsonl"
        task = {"category": "code-review"}
        err, ok = self.call("record_choice", task=task, offered=["user:alpha"], chosen="alpha")
        self.assertEqual((err, ok), (False, {"recorded": True, "chosen": "user:alpha"}))
        err, bad = self.call("record_choice", task=task, offered=["user:alpha"], chosen="nope")
        self.assertTrue(bad["error"].startswith("chosen:"))
        self.assertFalse(bad["recorded"])
        rows = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual([r["chosen"] for r in rows], ["user:alpha"])  # the unknown pick wrote nothing

    def test_initialize_does_not_claim_unknown_protocol_version(self):
        got = self.rpc("initialize", {"protocolVersion": "2099-01-01"})["result"]["protocolVersion"]
        self.assertNotEqual(got, "2099-01-01")
        self.assertRegex(got, r"^\d{4}-\d{2}-\d{2}$")

    def test_bad_json_line_returns_parse_error_and_continues(self):
        err = self.send_raw("{oops\n")
        self.assertEqual(err["error"]["code"], -32700)
        self.assertIn("result", self.rpc("ping"))

    def test_unknown_tool_is_error(self):
        res = self.rpc("tools/call", {"name": "nope", "arguments": {}})["result"]
        self.assertTrue(res["isError"])
        self.assertTrue(self.call("route", task={})[0])  # missing category: tool error, server alive
        self.assertEqual(self.rpc("no/such")["error"]["code"], -32601)
        self.assertIn("result", self.rpc("ping"))


if __name__ == "__main__":
    unittest.main()

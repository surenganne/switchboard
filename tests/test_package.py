import json
import re
import unittest
from pathlib import Path

from switchboard import frontmatter

ROOT = Path(__file__).resolve().parent.parent


def load(rel):
    return json.loads((ROOT / rel).read_text())


class PackageTest(unittest.TestCase):
    def referenced_files(self, obj):
        text = json.dumps(obj)
        return [ROOT / m for m in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"\\ ]+)", text)]

    def test_manifests_are_valid_json_and_consistent(self):
        plugin = load(".claude-plugin/plugin.json")
        market = load(".claude-plugin/marketplace.json")
        self.assertEqual(plugin["name"], "switchboard")
        self.assertEqual(plugin["license"], "MIT")
        self.assertEqual(market["name"], "switchboard")
        self.assertEqual([p["name"] for p in market["plugins"]], ["switchboard"])
        self.assertEqual(market["plugins"][0]["source"], "./")
        for rel in (".mcp.json", "hooks/hooks.json"):
            files = self.referenced_files(load(rel))
            self.assertTrue(files, rel)
            for f in files:
                self.assertTrue(f.is_file(), f)

    def test_version_matches_server(self):
        from switchboard import mcp_server
        self.assertEqual(load(".claude-plugin/plugin.json")["version"], mcp_server.VERSION)

    def test_commands_have_descriptions(self):
        names = {p.stem for p in (ROOT / "commands").glob("*.md")}
        self.assertEqual(names, {"profile", "status", "audit", "forget", "report"})
        for p in (ROOT / "commands").glob("*.md"):
            self.assertTrue((frontmatter.read(p) or {}).get("description"), p)


if __name__ == "__main__":
    unittest.main()

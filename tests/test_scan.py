import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from switchboard import paths, scan_claude


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def skill(name, desc):
    return f"---\nname: {name}\ndescription: {desc}\n---\nBody of {name}\n"


def build_fixture(root):
    """Fake claude_home + project dir. Returns (claude_home, project_dir)."""
    ch = root / "claude"
    proj = root / "proj"
    write(ch / "skills/alpha/SKILL.md", skill("alpha", "User skill alpha"))
    write(ch / "skills/broken/SKILL.md", "no frontmatter here\n")
    plug = root / "plugins/plug"
    write(plug / "skills/beta/SKILL.md", skill("beta", "Plugin skill beta"))
    write(plug / "commands/gamma-cmd.md", "---\ndescription: Plugin command gamma\n---\nDo it\n")
    off = root / "plugins/off"
    write(off / "skills/offskill/SKILL.md", skill("offskill", "Disabled plugin skill"))
    installed = {"plugins": {
        "plug@mkt": [{"installPath": str(plug)}],
        "off@mkt": [{"installPath": str(off)}],
        "gone@mkt": [{"installPath": str(root / "plugins/does-not-exist")}],
    }}
    write(ch / "plugins/installed_plugins.json", json.dumps(installed))
    write(ch / "settings.json", json.dumps({"enabledPlugins": {"plug@mkt": True, "off@mkt": True, "gone@mkt": True}}))
    # project settings disable `off` (later file wins)
    write(proj / ".claude/settings.json", json.dumps({"enabledPlugins": {"off@mkt": False}}))
    write(proj / ".claude/skills/delta/SKILL.md", skill("delta", "Project skill delta"))
    return ch, proj


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["SWITCHBOARD_HOME"] = str(self.root / "sbhome")
        self.ch, self.proj = build_fixture(self.root)
        self.phash = hashlib.sha256(str(self.proj.resolve()).encode()).hexdigest()[:8]

    def tearDown(self):
        os.environ.pop("SWITCHBOARD_HOME", None)
        self.tmp.cleanup()

    def ids(self):
        return {s["id"] for s in scan_claude.list_skills(self.ch, self.proj)}

    def test_lists_user_plugin_and_project_skills(self):
        self.assertEqual(self.ids(), {"user:alpha", "plug:beta", "plug:gamma-cmd", f"project:{self.phash}:delta"})
        rec = {s["id"]: s for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertEqual(rec["plug:gamma-cmd"]["kind"], "command")
        self.assertEqual(rec["plug:beta"]["source"], "plug")
        self.assertEqual(len(rec["user:alpha"]["content_hash"]), 16)

    def test_skips_disabled_missing_and_broken(self):
        ids = self.ids()
        for bad in ("off:offskill", "user:broken"):
            self.assertNotIn(bad, ids)
        self.assertFalse(any(i.startswith("gone:") for i in ids))
        # no project dir and corrupt installed_plugins.json: still no exception
        (self.ch / "plugins/installed_plugins.json").write_text("{oops")
        self.assertEqual({s["id"] for s in scan_claude.list_skills(self.ch, None)}, {"user:alpha"})

    def test_hash_changes_when_file_changes(self):
        before = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        write(self.ch / "skills/alpha/SKILL.md", skill("alpha", "User skill alpha") + "more\n")
        after = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertNotEqual(before["user:alpha"], after["user:alpha"])
        self.assertEqual(before["plug:beta"], after["plug:beta"])

    def test_inventory_file_is_private(self):
        p = scan_claude.write_inventory(scan_claude.list_skills(self.ch, self.proj))
        self.assertEqual(p, paths.home() / "inventory.json")
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)
        data = json.loads(p.read_text())
        self.assertEqual(data["version"], 1)
        self.assertIn("user:alpha", data["skills"])


if __name__ == "__main__":
    unittest.main()

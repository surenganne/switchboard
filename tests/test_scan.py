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

    def test_hygiene_fields(self):
        write(self.ch / "skills/long/SKILL.md", skill("long", "x" * 300))
        rec = {s["id"]: s for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertEqual(rec["plug:beta"]["plugin_key"], "plug@mkt")
        self.assertEqual(rec["plug:gamma-cmd"]["plugin_key"], "plug@mkt")
        self.assertNotIn("plugin_key", rec["user:alpha"])
        self.assertNotIn("plugin_key", rec[f"project:{self.phash}:delta"])
        self.assertEqual(rec["user:alpha"]["desc_chars"], len("User skill alpha"))
        self.assertEqual(rec["user:long"]["desc_chars"], 300)
        self.assertEqual(len(rec["user:long"]["description"]), 240)

    def test_skips_disabled_missing_and_broken(self):
        ids = self.ids()
        for bad in ("off:offskill", "user:broken"):
            self.assertNotIn(bad, ids)
        self.assertFalse(any(i.startswith("gone:") for i in ids))
        # no project dir and corrupt installed_plugins.json: still no exception
        (self.ch / "plugins/installed_plugins.json").write_text("{oops")
        self.assertEqual({s["id"] for s in scan_claude.list_skills(self.ch, None)}, {"user:alpha"})

    def test_bad_plugin_manifest_skills_field_does_not_crash(self):
        write(self.root / "plugins/plug/.claude-plugin/plugin.json", json.dumps({"skills": [1, None, "skills"]}))
        self.assertIn("plug:beta", self.ids())
        write(self.root / "plugins/plug/.claude-plugin/plugin.json", json.dumps({"skills": {"a": 1}}))
        self.assertIn("plug:beta", self.ids())

    def install(self, key, entries):
        f = self.ch / "plugins/installed_plugins.json"
        data = json.loads(f.read_text())
        data["plugins"][key] = entries
        f.write_text(json.dumps(data))
        s = json.loads((self.ch / "settings.json").read_text())
        s["enabledPlugins"][key] = True
        (self.ch / "settings.json").write_text(json.dumps(s))

    def test_install_entry_skips_missing_path_and_other_projects(self):
        good, other = self.root / "plugins/multi-good", self.root / "plugins/multi-other"
        write(good / "skills/good/SKILL.md", skill("good", "Good one"))
        write(other / "skills/other/SKILL.md", skill("other", "Other project's copy"))
        self.install("multi@mkt", [
            {"scope": "project", "projectPath": str(self.root / "elsewhere"), "installPath": str(other)},
            {"scope": "user", "installPath": str(self.root / "plugins/gone")},
            {"scope": "user", "installPath": str(good)}])
        ids = self.ids()
        self.assertIn("multi:good", ids)
        self.assertNotIn("multi:other", ids)
        # a project-scoped install for THIS project wins over the user one
        self.install("multi@mkt", [{"scope": "user", "installPath": str(good)},
                                   {"scope": "local", "projectPath": str(self.proj), "installPath": str(other)}])
        self.assertIn("multi:other", self.ids())

    def test_declared_skill_dirs_must_stay_inside_plugin(self):
        write(self.root / "outside/skills/sneaky/SKILL.md", skill("sneaky", "Outside the plugin"))
        write(self.root / "plugins/plug/.claude-plugin/plugin.json", json.dumps({"skills": ["../../outside/skills", "skills"]}))
        ids = self.ids()
        self.assertNotIn("plug:sneaky", ids)
        self.assertIn("plug:beta", ids)

    def test_declared_paths_add_to_default_dirs(self):
        plug = self.root / "plugins/plug"
        write(plug / "extra/epsilon/SKILL.md", skill("epsilon", "Extra skill"))
        write(plug / "more-cmds/zeta.md", "---\ndescription: Extra command\n---\n")
        write(plug / "single.md", "---\ndescription: Single file command\n---\n")
        write(plug / ".claude-plugin/plugin.json", json.dumps({"skills": "./extra", "commands": ["./more-cmds", "./single.md"]}))
        ids = self.ids()
        self.assertTrue({"plug:beta", "plug:epsilon", "plug:gamma-cmd", "plug:zeta", "plug:single"} <= ids, ids)

    def test_missing_description_falls_back_to_first_body_line(self):
        write(self.root / "plugins/plug/commands/bare.md", "\n# Bare command\nDoes bare things.\n")
        write(self.ch / "skills/nodesc/SKILL.md", "---\nname: nodesc\n---\n\nFirst line here.\nMore.\n")
        rec = {s["id"]: s for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertEqual(rec["plug:bare"]["description"], "Bare command")
        self.assertEqual(rec["user:nodesc"]["description"], "First line here.")
        self.assertNotIn("user:broken", rec)  # a SKILL.md with no frontmatter at all is still skipped

    def test_hash_covers_files_the_skill_points_to(self):
        write(self.ch / "skills/alpha/reference.md", "v1")
        before = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        write(self.ch / "skills/alpha/reference.md", "v2")
        after = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertNotEqual(before["user:alpha"], after["user:alpha"])

    def test_hash_changes_when_file_changes(self):
        before = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        write(self.ch / "skills/alpha/SKILL.md", skill("alpha", "User skill alpha") + "more\n")
        after = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertNotEqual(before["user:alpha"], after["user:alpha"])
        self.assertEqual(before["plug:beta"], after["plug:beta"])

    def test_hash_of_plain_folder_is_unchanged_from_rglob_version(self):
        # existing profiles stay valid: for a folder without symlinks the fingerprint matches the old rglob formula
        write(self.ch / "skills/alpha/reference.md", "ref")
        write(self.ch / "skills/alpha/deep/nested/notes.md", "notes")
        write(self.ch / "skills/alpha/.hidden/x.md", "hidden")
        sk = self.ch / "skills/alpha/SKILL.md"
        old = hashlib.sha256(sk.read_bytes())
        for p in sorted(p for p in sk.parent.rglob("*.md") if p != sk and p.is_file()):
            old.update(b"\0" + os.fsencode(p.relative_to(sk.parent)) + b"\0" + p.read_bytes())
        got = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertEqual(got["user:alpha"], old.hexdigest()[:16])

    def test_hash_does_not_follow_symlinked_folders(self):
        before = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        write(self.root / "outside/secret.md", "not part of the skill")
        os.symlink(self.root / "outside", self.ch / "skills/alpha/linked")
        os.symlink(self.ch / "skills/alpha", self.ch / "skills/alpha/loop")  # a cycle must not hang or crash
        after = {s["id"]: s["content_hash"] for s in scan_claude.list_skills(self.ch, self.proj)}
        self.assertEqual(before["user:alpha"], after["user:alpha"])

    def test_write_private_refuses_symlink_target(self):
        target = self.root / "outside.txt"
        target.write_text("keep")
        link = paths.home() / "evil.json"
        os.symlink(target, link)
        with self.assertRaises(OSError):
            paths.write_private(link, "overwrite")
        self.assertEqual(target.read_text(), "keep")

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

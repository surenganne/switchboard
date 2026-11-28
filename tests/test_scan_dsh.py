import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from switchboard import paths, scan_dsh


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def skill(name, desc):
    return f"---\nname: {name}\ndescription: {desc}\n---\nBody of {name}\n"


class ScanDshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._env_backup = {v: os.environ.get(v) for v in
                             ("SWITCHBOARD_HOME", "SWITCHBOARD_DSH_HOME", "DSH_PROJECT_DIR")}
        os.environ["SWITCHBOARD_HOME"] = str(self.root / "sbhome")
        dsh = self.root / "dsh"
        proj = self.root / "proj"
        write(dsh / "skills/alpha/SKILL.md", skill("alpha", "User skill alpha"))
        write(dsh / "skills/broken/SKILL.md", "no frontmatter here\n")
        write(proj / ".dsh/skills/delta/SKILL.md", skill("delta", "Project skill delta"))
        self.dsh, self.proj = dsh, proj
        self.phash = hashlib.sha256(str(proj.resolve()).encode()).hexdigest()[:8]
        # current() resolves dsh_home/project_dir via _homes(), not direct args
        os.environ["SWITCHBOARD_DSH_HOME"] = str(dsh)
        os.environ["DSH_PROJECT_DIR"] = str(proj)

    def tearDown(self):
        for v, old in self._env_backup.items():
            if old is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = old
        self.tmp.cleanup()

    def ids(self):
        return {s["id"] for s in scan_dsh.list_skills(self.dsh, self.proj)}

    def test_lists_user_and_project_skills(self):
        self.assertEqual(self.ids(), {"user:alpha", f"project:{self.phash}:delta"})
        rec = {s["id"]: s for s in scan_dsh.list_skills(self.dsh, self.proj)}
        self.assertEqual((rec["user:alpha"]["source"], rec["user:alpha"]["kind"]), ("user", "skill"))
        self.assertEqual(rec["user:alpha"]["path"], str(self.dsh / "skills/alpha/SKILL.md"))
        self.assertEqual(rec["user:alpha"]["name"], "alpha")
        self.assertEqual(rec["user:alpha"]["desc_chars"], len("User skill alpha"))
        self.assertEqual(len(rec["user:alpha"]["content_hash"]), 16)

    def test_skips_skills_without_frontmatter(self):
        self.assertNotIn("user:broken", self.ids())
        # no project dir: still no exception
        self.assertEqual({s["id"] for s in scan_dsh.list_skills(self.dsh, None)}, {"user:alpha"})

    def test_name_falls_back_to_folder_name(self):
        write(self.dsh / "skills/noname/SKILL.md", "---\ndescription: Named by folder\n---\nBody\n")
        rec = {s["id"]: s for s in scan_dsh.list_skills(self.dsh, None)}
        self.assertEqual(rec["user:noname"]["name"], "noname")

    def test_missing_description_falls_back_to_first_body_line(self):
        write(self.dsh / "skills/nodesc/SKILL.md", "---\nname: nodesc\n---\n\n# First line here.\nMore.\n")
        rec = {s["id"]: s for s in scan_dsh.list_skills(self.dsh, None)}
        self.assertEqual(rec["user:nodesc"]["description"], "First line here.")

    def test_description_is_capped_at_240_chars(self):
        write(self.dsh / "skills/long/SKILL.md", skill("long", "x" * 300))
        rec = {s["id"]: s for s in scan_dsh.list_skills(self.dsh, None)}
        self.assertEqual(len(rec["user:long"]["description"]), 240)
        self.assertEqual(rec["user:long"]["desc_chars"], 300)

    def test_hash_covers_files_the_skill_points_to(self):
        write(self.dsh / "skills/alpha/reference.md", "v1")
        before = {s["id"]: s["content_hash"] for s in scan_dsh.list_skills(self.dsh, None)}
        write(self.dsh / "skills/alpha/reference.md", "v2")
        after = {s["id"]: s["content_hash"] for s in scan_dsh.list_skills(self.dsh, None)}
        self.assertNotEqual(before["user:alpha"], after["user:alpha"])

    def test_hash_changes_when_skill_file_changes(self):
        before = {s["id"]: s["content_hash"] for s in scan_dsh.list_skills(self.dsh, self.proj)}
        write(self.dsh / "skills/alpha/SKILL.md", skill("alpha", "User skill alpha") + "more\n")
        after = {s["id"]: s["content_hash"] for s in scan_dsh.list_skills(self.dsh, self.proj)}
        self.assertNotEqual(before["user:alpha"], after["user:alpha"])
        self.assertEqual(before[f"project:{self.phash}:delta"], after[f"project:{self.phash}:delta"])

    def test_unhashed_scan_lists_same_skills_without_hashes(self):
        fast = scan_dsh.list_skills(self.dsh, self.proj, hashed=False)
        self.assertEqual({s["id"] for s in fast}, self.ids())
        self.assertFalse(any("content_hash" in s for s in fast))

    def test_current_resolves_homes_from_env(self):
        inv = scan_dsh.current(hashed=False)
        self.assertEqual(set(inv), {"user:alpha", f"project:{self.phash}:delta"})

    def test_write_inventory_shape(self):
        p = scan_dsh.write_inventory(scan_dsh.list_skills(self.dsh, self.proj))
        self.assertEqual(p, paths.home() / "inventory-dsh.json")
        data = json.loads(p.read_text())
        self.assertEqual(data["version"], 1)
        self.assertIn("user:alpha", data["skills"])
        self.assertIn("content_hash", data["skills"]["user:alpha"])


if __name__ == "__main__":
    unittest.main()

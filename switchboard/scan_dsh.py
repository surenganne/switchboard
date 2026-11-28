"""DeepSeek Harness (DSH) scanner: user and project skills.

Other platforms get their own scanner module exposing the same list_skills shape.
DSH keeps its skills as folders of markdown (a SKILL.md plus files it points to), so a skill's
fingerprint covers every .md in its folder, like scan_claude. DSH subagents have no files on
disk, so like Claude's built-ins they stay out of the scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from switchboard import frontmatter, paths


def project_source(project_dir: Path) -> str:
    return "project:" + hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:8]


FM_RE = re.compile(r"^---\s*\n.*?\n---\s*(\n|$)", re.S)
MAX_EXTRA_FILES, MAX_FILE_BYTES = 200, 1_000_000


def _first_line(text: str) -> str:
    m = FM_RE.match(text)
    for line in text[m.end() if m else 0:].splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return ""


def _hash(path: Path, data: bytes) -> str:
    """A skill's hash covers every .md in its folder (profiling reads them); SKILL.md itself counts."""
    h = hashlib.sha256(data)
    extra = sorted(p for p in path.parent.rglob("*.md") if p != path and p.is_file())[:MAX_EXTRA_FILES]
    for p in extra:
        try:
            if p.stat().st_size <= MAX_FILE_BYTES:
                # fsencode: a non-UTF-8 filename must not crash the whole scan
                h.update(b"\0" + os.fsencode(p.relative_to(path.parent)) + b"\0" + p.read_bytes())
        except OSError:
            continue
    return h.hexdigest()[:16]


def list_skills(dsh_home: Path, project_dir: Path | None, hashed: bool = True) -> list[dict]:
    """hashed=False skips content hashes (reading every .md in each skill folder): hooks need only ids, fast."""
    out: dict[str, dict] = {}

    def add(source, name, path, fm=False):
        sid = f"{source}:{name}"
        if sid in out:
            return
        try:
            data = path.read_bytes()
        except OSError:
            return
        text = data.decode("utf-8", errors="replace")
        if fm is False:  # False: not parsed yet (None means the file has no frontmatter)
            fm = frontmatter.read(path)
        if fm is None:  # without frontmatter a skill is not loadable
            return
        desc = " ".join(str(fm.get("description") or "").split()) or _first_line(text)
        if not desc:
            return
        out[sid] = {"id": sid, "name": name, "source": source, "kind": "skill", "path": str(path),
                    "description": desc[:240], "desc_chars": len(desc)}
        if hashed:
            out[sid]["content_hash"] = _hash(path, data)

    def skills_in(d, source):
        for sk in sorted(d.glob("*/SKILL.md")):
            fm = frontmatter.read(sk)
            add(source, str((fm or {}).get("name") or sk.parent.name), sk, fm)

    skills_in(dsh_home / "skills", "user")

    if project_dir is not None:
        skills_in(project_dir / ".dsh/skills", project_source(project_dir))

    return list(out.values())


def _homes() -> tuple[Path, Path]:
    """(dsh_home, project_dir) for this session (env overrides for tests)."""
    return (Path(os.environ.get("SWITCHBOARD_DSH_HOME") or Path.home() / ".dsh"),
            Path(os.environ.get("DSH_PROJECT_DIR") or os.getcwd()))


def current(hashed: bool = True) -> dict:
    """Skills mapping {id: record} for this session."""
    return {s["id"]: s for s in list_skills(*_homes(), hashed)}


def write_inventory(skills: list[dict]) -> Path:
    """Write DSH skills to their own inventory file. `scan_claude` writes Claude's inventory at
    SessionStart and `usage.cached_inventory()` reads it, so overwriting `inventory.json` from here
    would replace the Claude inventory with DSH-only skills; DSH skills land in `inventory-dsh.json`
    until the scanner is wired into the hooks."""
    p = paths.home() / "inventory-dsh.json"
    paths.write_private(p, json.dumps({"version": 1, "skills": {s["id"]: s for s in skills}}, indent=1, sort_keys=True))
    return p

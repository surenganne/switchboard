"""Claude Code scanner: user, project and enabled-plugin skills and commands.

Other platforms get their own scanner module exposing the same list_skills shape.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from switchboard import frontmatter, paths


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def skill_dirs(root: Path) -> list[Path]:
    """Skill folders for a plugin root: the plugin.json `skills` field if set, else ./skills."""
    declared = _json(root / ".claude-plugin" / "plugin.json").get("skills")
    if isinstance(declared, str):
        declared = [declared]
    declared = [d for d in declared if isinstance(d, str)] if isinstance(declared, list) else None
    dirs = [(root / d).resolve() for d in declared] if declared else [root / "skills"]
    return [d for d in dirs if d.is_dir()]


def project_source(project_dir: Path) -> str:
    return "project:" + hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:8]


def list_skills(claude_home: Path, project_dir: Path | None) -> list[dict]:
    out: dict[str, dict] = {}

    def add(source, name, kind, path):
        sid = f"{source}:{name}"
        if sid in out:
            return
        try:
            data = path.read_bytes()
        except OSError:
            return
        fm = frontmatter.read(path) or {}
        desc = " ".join(str(fm.get("description") or "").split())
        if not desc:
            return
        out[sid] = {"id": sid, "name": name, "source": source, "kind": kind, "path": str(path),
                    "description": desc, "content_hash": hashlib.sha256(data).hexdigest()[:16]}

    def skills_in(d, source):
        for sk in sorted(d.glob("*/SKILL.md")):
            add(source, str((frontmatter.read(sk) or {}).get("name") or sk.parent.name), "skill", sk)

    def commands_in(d, source):
        for cmd in sorted(d.glob("*.md")):
            add(source, cmd.stem, "command", cmd)

    skills_in(claude_home / "skills", "user")

    settings = [claude_home / "settings.json"]
    if project_dir is not None:
        src = project_source(project_dir)
        skills_in(project_dir / ".claude/skills", src)
        commands_in(project_dir / ".claude/commands", src)
        settings += [project_dir / ".claude/settings.json", project_dir / ".claude/settings.local.json"]

    enabled: dict = {}
    for s in settings:  # later file wins
        ep = _json(s).get("enabledPlugins")
        if isinstance(ep, dict):
            enabled.update(ep)
    installed = _json(claude_home / "plugins/installed_plugins.json").get("plugins") or {}
    for key in sorted(k for k, v in enabled.items() if v):
        try:
            root = Path(installed[key][0]["installPath"])
        except (KeyError, IndexError, TypeError):
            continue
        plugin = key.split("@")[0]
        try:  # one odd third-party plugin must not take down the whole scan
            for d in skill_dirs(root):
                skills_in(d, plugin)
            commands_in(root / "commands", plugin)
        except (OSError, TypeError, ValueError):
            continue
    return list(out.values())


def current() -> dict:
    """Skills mapping {id: record} for this session (env overrides for tests)."""
    claude_home = Path(os.environ.get("SWITCHBOARD_CLAUDE_HOME") or Path.home() / ".claude")
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    return {s["id"]: s for s in list_skills(claude_home, project)}


def write_inventory(skills: list[dict]) -> Path:
    p = paths.home() / "inventory.json"
    paths.write_private(p, json.dumps({"version": 1, "skills": {s["id"]: s for s in skills}}, indent=1, sort_keys=True))
    return p

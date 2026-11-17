"""Claude Code scanner: user, project and enabled-plugin skills, commands and agents (subagents).

Other platforms get their own scanner module exposing the same list_skills shape.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from switchboard import frontmatter, paths


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def plugin_paths(root: Path, field: str) -> list[Path]:
    """The default ./<field> folder plus any paths plugin.json declares for it (custom paths add to the
    default, they do not replace it), kept only when they stay inside the plugin."""
    declared = _json(root / ".claude-plugin" / "plugin.json").get(field)
    if isinstance(declared, str):
        declared = [declared]
    declared = [d for d in declared if isinstance(d, str)] if isinstance(declared, list) else []
    base = root.resolve()
    out = []
    for p in [root / field] + [root / d for d in declared]:
        p = p.resolve()
        # a manifest must not point the scanner outside its own plugin
        if p.exists() and (p == base or base in p.parents) and p not in out:
            out.append(p)
    return out


def skill_dirs(root: Path) -> list[Path]:
    return [d for d in plugin_paths(root, "skills") if d.is_dir()]


def install_root(entries, project_dir: Path | None) -> Path | None:
    """Pick the install for this project: a project/local install for this project first, else a
    general (user) install; entries whose path is gone are skipped."""
    if not isinstance(entries, list):
        return None
    proj = str(project_dir.resolve()) if project_dir is not None else None
    ok = [e for e in entries if isinstance(e, dict) and isinstance(e.get("installPath"), str)
          and Path(e["installPath"]).is_dir()]
    mine = [e for e in ok if isinstance(e.get("projectPath"), str) and proj
            and str(Path(e["projectPath"]).resolve()) == proj]
    general = [e for e in ok if not e.get("projectPath")]
    pick = (mine or general or [None])[0]
    return Path(pick["installPath"]) if pick else None


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


def _hash(path: Path, kind: str, data: bytes) -> str:
    """A skill's hash covers every .md in its folder (profiling reads them); a command's, its own file."""
    h = hashlib.sha256(data)
    if kind == "skill":
        extra = sorted(p for p in path.parent.rglob("*.md") if p != path and p.is_file())[:MAX_EXTRA_FILES]
        for p in extra:
            try:
                if p.stat().st_size <= MAX_FILE_BYTES:
                    # fsencode: a non-UTF-8 filename must not crash the whole scan
                    h.update(b"\0" + os.fsencode(p.relative_to(path.parent)) + b"\0" + p.read_bytes())
            except OSError:
                continue
    return h.hexdigest()[:16]


def enabled_plugins(claude_home: Path, project_dir: Path | None) -> list[tuple[str, Path]]:
    """(settings key, install root) of each enabled, installed plugin, sorted by key."""
    settings = [claude_home / "settings.json"]
    if project_dir is not None:
        settings += [project_dir / ".claude/settings.json", project_dir / ".claude/settings.local.json"]
    enabled: dict = {}
    for s in settings:  # later file wins
        ep = _json(s).get("enabledPlugins")
        if isinstance(ep, dict):
            enabled.update(ep)
    installed = _json(claude_home / "plugins/installed_plugins.json").get("plugins") or {}
    out = []
    for key in sorted(k for k, v in enabled.items() if v):
        root = install_root(installed.get(key) if isinstance(installed, dict) else None, project_dir)
        if root is not None:
            out.append((key, root))
    return out


def mcp_servers(root: Path) -> list[str]:
    """Names of the MCP servers a plugin starts: its .mcp.json plus plugin.json's mcpServers (inline, or paths
    to files of the same shape as .mcp.json, kept inside the plugin)."""
    found = {}
    for f in [root / ".mcp.json"] + [p for p in plugin_paths(root, "mcpServers") if p.is_file()]:
        servers = _json(f).get("mcpServers")
        if isinstance(servers, dict):
            found.update(servers)
    inline = _json(root / ".claude-plugin" / "plugin.json").get("mcpServers")
    if isinstance(inline, dict):
        found.update(inline)
    return sorted(k for k in found if isinstance(k, str))


def plugin_mcp(claude_home: Path, project_dir: Path | None) -> dict[str, list[str]]:
    """{plugin settings key: MCP server names} for enabled plugins that start any."""
    out = {}
    for key, root in enabled_plugins(claude_home, project_dir):
        try:  # one odd third-party plugin must not take down the whole lookup
            names = mcp_servers(root)
        except (OSError, TypeError, ValueError):
            continue
        if names:
            out[key] = names
    return out


def list_skills(claude_home: Path, project_dir: Path | None, hashed: bool = True) -> list[dict]:
    """hashed=False skips content hashes (reading every .md in each skill folder): hooks need only ids, fast."""
    out: dict[str, dict] = {}

    def add(source, name, kind, path, fm=False):
        sid = f"{source}:{name}"
        # agents are their own namespace in Claude Code: one named like a skill or command gets a kind-qualified id
        # (agents are scanned after skills and commands of the same source; a plugin's command shim for its own
        # same-named skill is the same thing twice, so the first one keeps the id)
        if sid in out and kind == "agent" and out[sid]["kind"] != "agent":
            sid = f"{source}:agent:{name}"
        if sid in out:
            return
        try:
            data = path.read_bytes()
        except OSError:
            return
        text = data.decode("utf-8", errors="replace")
        if fm is False:  # False: not parsed yet (None means the file has no frontmatter)
            fm = frontmatter.read(path)
        if fm is None and kind in ("skill", "agent"):  # without frontmatter neither is loadable
            return
        desc = " ".join(str((fm or {}).get("description") or "").split()) or _first_line(text)
        if not desc:
            return
        out[sid] = {"id": sid, "name": name, "source": source, "kind": kind, "path": str(path),
                    "description": desc[:240], "desc_chars": len(desc)}
        if hashed:
            out[sid]["content_hash"] = _hash(path, kind, data)

    def skills_in(d, source):
        for sk in sorted(d.glob("*/SKILL.md")):
            add(source, str((frontmatter.read(sk) or {}).get("name") or sk.parent.name), "skill", sk)

    def commands_in(d, source):
        for cmd in sorted(d.glob("*.md")):
            add(source, cmd.stem, "command", cmd)

    def agent(path, source):
        fm = frontmatter.read(path)
        add(source, str((fm or {}).get("name") or path.stem), "agent", path, fm)

    def agents_in(d, source):
        for a in sorted(d.glob("*.md")):
            agent(a, source)

    skills_in(claude_home / "skills", "user")
    commands_in(claude_home / "commands", "user")
    agents_in(claude_home / "agents", "user")

    if project_dir is not None:
        src = project_source(project_dir)
        skills_in(project_dir / ".claude/skills", src)
        commands_in(project_dir / ".claude/commands", src)
        agents_in(project_dir / ".claude/agents", src)

    for key, root in enabled_plugins(claude_home, project_dir):
        plugin = key.split("@")[0]
        try:  # one odd third-party plugin must not take down the whole scan
            for d in skill_dirs(root):
                skills_in(d, plugin)
            for c in plugin_paths(root, "commands"):
                if c.is_dir():
                    commands_in(c, plugin)
                elif c.suffix == ".md":
                    add(plugin, c.stem, "command", c)
            for a in plugin_paths(root, "agents"):
                if a.is_dir():
                    agents_in(a, plugin)
                elif a.suffix == ".md":
                    agent(a, plugin)
        except (OSError, TypeError, ValueError):
            continue
        for rec in out.values():  # the settings key hygiene tells the user to disable
            if rec["source"] == plugin:
                rec.setdefault("plugin_key", key)
    return list(out.values())


def _homes() -> tuple[Path, Path]:
    """(claude_home, project_dir) for this session (env overrides for tests)."""
    return (Path(os.environ.get("SWITCHBOARD_CLAUDE_HOME") or Path.home() / ".claude"),
            Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()))


def current(hashed: bool = True) -> dict:
    """Skills mapping {id: record} for this session."""
    return {s["id"]: s for s in list_skills(*_homes(), hashed)}


def current_mcp() -> dict[str, list[str]]:
    return plugin_mcp(*_homes())


def write_inventory(skills: list[dict]) -> Path:
    p = paths.home() / "inventory.json"
    paths.write_private(p, json.dumps({"version": 1, "skills": {s["id"]: s for s in skills}}, indent=1, sort_keys=True))
    return p

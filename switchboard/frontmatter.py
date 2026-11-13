"""Minimal YAML frontmatter reader (ported unchanged from ~/.skill-prefs/registry.py)."""
from __future__ import annotations

import json
import re
from pathlib import Path

BLOCK_SCALARS = {">", ">-", ">+", "|", "|-", "|+"}
TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):(?:[ \t]+(.*))?$")


def _unquote(val):
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        try:
            return json.loads(val)
        except ValueError:
            return val[1:-1]
    if len(val) >= 2 and val[0] == "'" and val[-1] == "'":
        return val[1:-1].replace("''", "'")
    return val


def parse(block):
    """Minimal YAML subset: top-level `key: value`, quoted scalars, folded/literal blocks,
    plain multi-line scalars. Nested mappings and lists are skipped, since only the top-level
    name and description are needed."""
    lines = block.splitlines()
    data, i = {}, 0
    while i < len(lines):
        m = TOP_KEY.match(lines[i])
        i += 1
        if not m:
            continue
        key, val = m.group(1), (m.group(2) or "").strip()
        cont = []
        while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t"):
            cont.append(lines[i].strip())
            i += 1
        if val in BLOCK_SCALARS:
            data[key] = " ".join(c for c in cont if c)
        elif val == "":
            data[key] = None  # nested structure: not needed
        else:
            data[key] = _unquote(" ".join([val] + [c for c in cont if c]))
    return data


def read(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    return parse(m.group(1)) if m else None

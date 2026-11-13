"""Local log of which skills were used, for hygiene. Stores skill id and date only, never prompt text.

`usage.jsonl`: one {"date", "id"} row per use. `first_seen.json`: {id: date first seen installed}.
"""
from __future__ import annotations

import json
from datetime import date

from switchboard import paths


def _log():
    return paths.home() / "usage.jsonl"


def _seen():
    return paths.home() / "first_seen.json"


def recording_on() -> bool:
    try:
        return json.loads((paths.home() / "settings.json").read_text()).get("record_usage", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def cached_inventory() -> dict:
    """shortcut: uses the last session's inventory, so a skill installed mid-session is logged from the next session"""
    try:
        skills = json.loads((paths.home() / "inventory.json").read_text()).get("skills")
    except (OSError, ValueError, AttributeError):
        return {}
    return skills if isinstance(skills, dict) else {}


def resolve(name: str, inv: dict):
    """Installed skill id for a name as Claude or the user wrote it, or None (so free text is never stored)."""
    if name in inv:
        return name
    if f"user:{name}" in inv:
        return f"user:{name}"
    proj = [i for i in inv if i.startswith("project:") and i.split(":", 2)[-1] == name]
    return proj[0] if len(proj) == 1 else None


def record(ids, today=None) -> None:
    ids = [i for i in ids if isinstance(i, str)]
    if not ids or not recording_on():
        return
    log = _log()
    if not log.exists():
        paths.write_private(log, "")
    day = today or date.today().isoformat()
    with log.open("a", encoding="utf-8") as f:
        for i in ids:
            f.write(json.dumps({"date": day, "id": i}, sort_keys=True) + "\n")


def rows() -> list:
    try:
        text = _log().read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("date"), str) and isinstance(row.get("id"), str):
            out.append(row)
    return out


def first_seen() -> dict:
    try:
        data = json.loads(_seen().read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def note_seen(ids, today=None) -> None:
    seen = first_seen()
    day = today or date.today().isoformat()
    new = {i: day for i in ids if isinstance(i, str) and i not in seen}
    if new:
        seen.update(new)
        paths.write_private(_seen(), json.dumps(seen, sort_keys=True))


def forget() -> int:
    """Delete the usage log and first-seen dates together: keeping the dates would make every skill look unused."""
    n = len(rows())
    for p in (_log(), _seen()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    return n

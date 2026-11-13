"""Local log of which skill the user picked. Labels only: never feeds back into scoring.

Stores task features and skill ids only. No prompt text, no code: free text in feature fields
is dropped by keeping schema values only.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from switchboard import paths, profiles

FEATURES = ("category", "targets", "focus", "stack", "depth", "cost")


def _log():
    return paths.home() / "choices.jsonl"


def features(task: dict) -> dict:
    def keep(key, allowed):
        v = task.get(key)
        v = v if isinstance(v, list) else [v] if isinstance(v, str) else []
        return sorted({x for x in v if allowed(x)})

    one = lambda key, allowed: task.get(key) if task.get(key) in allowed else None
    return {
        "category": one("category", profiles.CATEGORIES),
        "targets": keep("targets", profiles.TARGETS.__contains__),
        "focus": keep("focus", profiles.FOCUS.__contains__),
        "stack": keep("stack", lambda x: isinstance(x, str) and len(x) <= 30 and bool(profiles.STACK_RE.match(x))),
        "depth": one("depth", profiles.DEPTHS),
        "cost": one("cost", profiles.COSTS),
    }


def _recording_on() -> bool:
    try:
        return json.loads((paths.home() / "settings.json").read_text()).get("record_choices", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def record(task: dict, offered: list[str], chosen: str) -> None:
    if not _recording_on():
        return
    ids = lambda xs: [x for x in xs if isinstance(x, str) and len(x) <= 200][:10]
    row = dict(features(task), date=date.today().isoformat(), offered=ids(offered or []),
               chosen=chosen if isinstance(chosen, str) and len(chosen) <= 200 else None)
    log = _log()
    if not log.exists():
        paths.write_private(log, "")
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _rows() -> list[dict]:
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
        if isinstance(row, dict):
            out.append(row)
    return out


def _bag(row: dict) -> set:
    return set(row.get("targets") or []) | set(row.get("focus") or [])


def similar(task: dict) -> list[dict]:
    f = features(task)
    want = _bag(f)
    out = []
    for row in _rows():
        if row.get("category") != f["category"]:
            continue
        have = _bag(row)
        union = want | have
        if not union or len(want & have) / len(union) >= 0.5:
            out.append(row)
    return out


def audit() -> list[dict]:
    groups = defaultdict(list)
    for row in _rows():
        offered = row.get("offered") or []
        if offered and row.get("chosen") != offered[0]:
            key = (row.get("category"), tuple(sorted(row.get("targets") or [])), tuple(sorted(row.get("focus") or [])))
            groups[key].append(row.get("chosen"))
    return [{"category": c, "targets": list(t), "focus": list(f), "overrides": len(picked), "chosen": sorted(set(picked))}
            for (c, t, f), picked in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))
            if len(picked) >= 2]


def forget() -> int:
    n = len(_rows())
    try:
        _log().unlink()
    except FileNotFoundError:
        pass
    return n

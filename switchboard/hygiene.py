"""Skill hygiene: which installed plugins and user/project skills went unused, and the context they cost.

Pure: takes the inventory, usage rows and first-seen dates, returns suggestions. Never changes settings.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

DEFAULT_DAYS, MIN_DAYS, MAX_DAYS = 30, 7, 365
MOSTLY_UNUSED = 0.2  # a plugin where at most 1 in 5 skills was used


def tokens(rec: dict) -> int:
    """Rough cost of one entry in the skill list: ~4 characters per token, plus list formatting."""
    chars = rec.get("desc_chars")
    if not isinstance(chars, int):
        chars = len(rec.get("description") or "")
    return math.ceil((len(rec.get("name") or "") + 1 + chars) / 4) + 10


def _days(days) -> int:
    try:
        return max(MIN_DAYS, min(int(days), MAX_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_DAYS


def _date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def suggest(inv: dict, rows: list, seen: dict, today: str, days=DEFAULT_DAYS, recording: bool = True) -> dict:
    if not recording:
        return {"recording": False}
    days, now = _days(days), date.fromisoformat(today)
    dates = [d for d in map(_date, seen.values()) if d]
    logged = (now - min(dates)).days if dates else 0
    if logged < days:
        return {"collecting": True, "days_logged": logged, "window_days": days}

    start = (now - timedelta(days=days)).isoformat()
    used = {r["id"] for r in rows if r.get("date", "") >= start and r.get("id") in inv}
    old = lambda sid: seen.get(sid, today) <= start  # never seen counts as new, so it is not suggested

    plugins, mostly, skills = [], [], []
    groups = defaultdict(list)
    for sid, rec in inv.items():
        if rec.get("source") == "switchboard":
            continue
        if rec.get("plugin_key"):
            groups[rec["plugin_key"]].append(sid)
        elif sid not in used and old(sid):
            skills.append({"id": sid, "path": rec.get("path"), "tokens": tokens(rec)})
    for key, members in groups.items():
        cost = sum(tokens(inv[sid]) for sid in members)
        hit = sorted(sid for sid in members if sid in used)
        if not hit and min(seen.get(sid, today) for sid in members) <= start:
            plugins.append({"plugin_key": key, "skills": len(members), "tokens": cost})
        elif hit and len(hit) / len(members) <= MOSTLY_UNUSED:
            mostly.append({"plugin_key": key, "used": hit, "skills": len(members), "tokens": cost})

    by_cost = lambda x: -x["tokens"]
    now_total = sum(tokens(r) for r in inv.values())
    return {"collecting": False, "window_days": days,
            "plugins": sorted(plugins, key=by_cost), "mostly_unused": sorted(mostly, key=by_cost),
            "skills": sorted(skills, key=by_cost), "tokens_now": now_total,
            "tokens_after": now_total - sum(p["tokens"] for p in plugins) - sum(s["tokens"] for s in skills)}

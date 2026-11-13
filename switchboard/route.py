"""Score profiled skills against Claude's structured description of a task.

Past choices are attached as labels after scoring and never change the order.
"""
from __future__ import annotations

from collections import Counter

W_TARGET, W_FOCUS, W_STACK, W_DEPTH, W_COST = 3, 2, 1, 1, 1
LIMIT = 5
FULL_TAGS = 3  # a field with more tags than this is discounted


def _list(v):
    return v if isinstance(v, list) else [v] if isinstance(v, str) else []


def _fit(task_vals, prof_vals) -> float:
    """Share of the task's tags the profile covers, so a skill that matches only part of the task
    ranks below one that matches all of it; a field listing more than FULL_TAGS tags is scaled by
    FULL_TAGS/len, so a tag-stuffed profile cannot buy a top rank."""
    task, prof = set(_list(task_vals)), set(prof_vals or [])
    if not task or not prof:
        return 0.0
    return len(task & prof) / len(task) * min(1.0, FULL_TAGS / len(prof))


def _precision(task: dict, p: dict) -> float:
    """Tie-break only: matched share of the profile's own target and focus tags (the more focused skill first)."""
    return sum(len(set(_list(task.get(k))) & set(p.get(k) or [])) / len(p.get(k)) for k in ("targets", "focus") if p.get(k))


def score(task: dict, p: dict) -> float:
    s = W_TARGET * _fit(task.get("targets"), p.get("targets"))
    s += W_FOCUS * _fit(task.get("focus"), p.get("focus"))
    stack = set(_list(task.get("stack")))
    if stack and ("any" in (p.get("stack") or []) or stack & set(p.get("stack") or [])):
        s += W_STACK
    if task.get("depth") and task.get("depth") == p.get("depth"):
        s += W_DEPTH
    if task.get("cost") and task.get("cost") == p.get("cost"):
        s += W_COST
    return round(s, 2)


def route(task: dict, profiles: dict, inventory: dict, past: list[dict]) -> dict:
    """`profiles` {id: profile}; `inventory` the current skills mapping {id: record}."""
    cat = task.get("category") if isinstance(task, dict) else None
    if not isinstance(cat, str) or not cat:
        raise ValueError("task.category is required")
    scored = [(score(task, p), _precision(task, p), sid) for sid, p in profiles.items()
              if sid in inventory and cat in (p.get("categories") or [])]
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    cands = []
    for s, _, sid in scored[:LIMIT]:
        p = profiles[sid]
        cands.append({"id": sid, "score": s, "stale": p.get("content_hash") != inventory[sid].get("content_hash"),
                      "profile": p,
                      "past_choices": [r.get("date") for r in past if r.get("chosen") == sid]})
    return {"candidates": cands, "overlap": len(cands) >= 2}


def overlap_categories(profiles: dict, inventory: dict) -> list[str]:
    n = Counter(c for sid, p in profiles.items() if sid in inventory for c in set(p.get("categories") or []))
    return sorted(c for c, k in n.items() if k >= 2)

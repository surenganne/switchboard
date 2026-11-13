"""Skill profiles: fixed schema, strict validator, private store.

Profiles are written by Claude from skill text, so skill text is untrusted: only schema fields,
enum values and capped lengths get through.
"""
from __future__ import annotations

import hashlib
import json
import re

from switchboard import paths

CATEGORIES = ("code-review", "debugging", "testing", "security", "ui-design", "planning", "docs",
              "git-release", "cloud-devops", "data", "language-framework", "other")
TARGETS = ("pr", "local-diff", "files", "repo", "url", "design", "infra", "data", "docs", "prompt")
FOCUS = ("security", "correctness", "bloat", "performance", "merge-readiness", "accessibility",
         "style", "tests", "architecture", "ux", "cost", "reliability")
DEPTHS = ("quick", "standard", "thorough")
COSTS = ("single-pass", "multi-agent", "workflow")
KEYS = {"id", "source", "content_hash", "categories", "does", "targets", "focus", "depth", "cost",
        "stack", "best_for", "not_for"}
STACK_RE = re.compile(r"^[a-z0-9.+#-]+$")


def _enum_list(p, key, allowed, lo, hi, errs):
    v = p.get(key)
    if not isinstance(v, list) or not lo <= len(v) <= hi or any(x not in allowed for x in v):
        errs.append(f"{key}: {lo}-{hi} values from {', '.join(allowed)}")


def _phrases(p, key, n, size, errs):
    v = p.get(key)
    if not isinstance(v, list) or len(v) > n or any(
            not isinstance(x, str) or len(x) > size or "\n" in x or "\r" in x for x in v):
        errs.append(f"{key}: up to {n} single-line strings of at most {size} chars")


def validate(p: dict, inventory: dict) -> list[str]:
    """`inventory` is the skills mapping {id: record}. Empty list means valid."""
    if not isinstance(p, dict):
        return ["profile must be an object"]
    errs = []
    if set(p) != KEYS:
        extra, missing = sorted(set(p) - KEYS), sorted(KEYS - set(p))
        errs.append(f"keys must be exactly the schema fields (extra: {extra}, missing: {missing})")
    rec = inventory.get(p.get("id")) if isinstance(p.get("id"), str) else None
    if rec is None:
        errs.append("id: not in the current inventory")
    elif p.get("content_hash") != rec.get("content_hash"):
        errs.append("content_hash: does not match the inventory")
    if not isinstance(p.get("source"), str) or len(p["source"]) > 100:
        errs.append("source: string of at most 100 chars")
    _enum_list(p, "categories", CATEGORIES, 1, 3, errs)
    _enum_list(p, "targets", TARGETS, 0, 6, errs)
    _enum_list(p, "focus", FOCUS, 0, 6, errs)
    if p.get("depth") not in DEPTHS:
        errs.append(f"depth: one of {', '.join(DEPTHS)}")
    if p.get("cost") not in COSTS:
        errs.append(f"cost: one of {', '.join(COSTS)}")
    st = p.get("stack")
    if not isinstance(st, list) or not 1 <= len(st) <= 8 or any(
            not isinstance(x, str) or len(x) > 30 or not STACK_RE.match(x) for x in st):
        errs.append("stack: 1-8 lowercase tags ([a-z0-9.+#-], at most 30 chars) or [\"any\"]")
    d = p.get("does")
    if not isinstance(d, str) or not d or len(d) > 200 or "\n" in d or "\r" in d:
        errs.append("does: one line, 1-200 chars")
    _phrases(p, "best_for", 5, 80, errs)
    _phrases(p, "not_for", 5, 80, errs)
    return errs


def _file(sid: str):
    return paths.home() / "profiles" / (hashlib.sha256(sid.encode()).hexdigest()[:16] + ".json")


def save(p: dict, inventory: dict) -> list[str]:
    errs = validate(p, inventory)
    if not errs:
        paths.write_private(_file(p["id"]), json.dumps(p, indent=1, sort_keys=True))
    return errs


def load_all() -> dict[str, dict]:
    out = {}
    for f in sorted((paths.home() / "profiles").glob("*.json")):
        try:
            p = json.loads(f.read_text())
            out[p["id"]] = p
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def pending(inventory: dict) -> list[dict]:
    have = load_all()
    out = []
    for sid in sorted(inventory):
        rec = inventory[sid]
        prof = have.get(sid)
        if prof is None or prof.get("content_hash") != rec.get("content_hash"):
            out.append({"id": sid, "path": rec.get("path"), "reason": "new" if prof is None else "changed"})
    return out

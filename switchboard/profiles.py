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
              "git-release", "cloud-devops", "data", "language-framework", "video-editing",
              "browser-automation", "gstack-tooling", "session-safety-guards", "session-checkpointing",
              "ios-debug-bridge", "other")
TARGETS = ("pr", "local-diff", "files", "repo", "url", "design", "infra", "data", "docs", "prompt")
FOCUS = ("security", "correctness", "bloat", "performance", "merge-readiness", "accessibility",
         "style", "tests", "architecture", "ux", "cost", "reliability", "skill-routing", "session-continuity")
DEPTHS = ("quick", "standard", "thorough")
COSTS = ("single-pass", "multi-agent", "workflow")
ROLES = ("performs", "assists", "meta")  # does the task / works around it / manages skills, settings or the agent
KEYS = {"id", "source", "content_hash", "categories", "does", "targets", "focus", "depth", "cost",
        "stack", "best_for", "not_for"}
OPTIONAL = {"role", "domain", "focus_tag", "target_tag"}  # role: backfilled later; domain/focus_tag/target_tag:
# free tags for when the closed `categories`/`focus`/`targets` enums don't fit a skill (`other` or empty)
STACK_RE = re.compile(r"^[a-z0-9.+#-]+$")
TAG_MAX = 40


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
    if set(p) - OPTIONAL != KEYS:
        extra, missing = sorted(set(p) - KEYS - OPTIONAL), sorted(KEYS - set(p))
        errs.append(f"keys must be exactly the schema fields (extra: {extra}, missing: {missing})")
    if "role" in p and p["role"] not in ROLES:
        errs.append(f"role: one of {', '.join(ROLES)}")
    for key in ("domain", "focus_tag", "target_tag"):
        cats = p.get("categories")
        applicable = (key == "domain" and isinstance(cats, list) and "other" in cats
                      or key == "focus_tag" and not p.get("focus")
                      or key == "target_tag" and not p.get("targets"))
        if key in p and (not applicable or not isinstance(p[key], str) or not p[key]
                         or len(p[key]) > TAG_MAX or not STACK_RE.match(p[key])):
            errs.append(f"{key}: a lowercase tag ([a-z0-9.+#-], at most {TAG_MAX} chars)")
    rec = inventory.get(p.get("id")) if isinstance(p.get("id"), str) else None
    if rec is None:
        errs.append("id: not in the current inventory")
    elif p.get("content_hash") != rec.get("content_hash"):
        errs.append("content_hash: does not match the inventory")
    if not isinstance(p.get("source"), str) or len(p["source"]) > 100:
        errs.append("source: string of at most 100 chars")
    elif rec is not None and "source" in rec and p["source"] != rec["source"]:
        errs.append("source: does not match the inventory")
    _enum_list(p, "categories", CATEGORIES, 1, 3, errs)
    _enum_list(p, "targets", TARGETS, 0, 6, errs)
    _enum_list(p, "focus", FOCUS, 0, 6, errs)
    if p.get("depth") not in DEPTHS:
        errs.append(f"depth: one of {', '.join(DEPTHS)}")
    if p.get("cost") not in COSTS:
        errs.append(f"cost: one of {', '.join(COSTS)}")
    elif rec is not None and rec.get("kind") == "agent" and p["cost"] != "multi-agent":
        errs.append("cost: an agent always runs as a subagent, so its cost is multi-agent")
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


def set_role(sid, content_hash, role, inventory: dict) -> list[str]:
    """Add or change only the role of an existing, current profile."""
    if role not in ROLES:
        return [f"role: one of {', '.join(ROLES)}"]
    p = load_all().get(sid) if isinstance(sid, str) else None
    if p is None or sid not in inventory:
        return ["id: no saved profile for an installed skill with this id"]
    if content_hash != p["content_hash"] or content_hash != inventory[sid].get("content_hash"):
        return ["content_hash: the skill changed since it was profiled; re-profile it instead"]
    return save(dict(p, role=role), inventory)


def pending_roles(inventory: dict) -> list[dict]:
    """Installed, current profiles that have no role yet."""
    return [{"id": sid, "content_hash": p["content_hash"]} for sid, p in sorted(load_all().items())
            if "role" not in p and sid in inventory and p["content_hash"] == inventory[sid].get("content_hash")]


def _set_tag(key: str, sid, content_hash, value, inventory: dict) -> list[str]:
    if not isinstance(value, str) or not value or len(value) > TAG_MAX or not STACK_RE.match(value):
        return [f"{key}: a lowercase tag ([a-z0-9.+#-], at most {TAG_MAX} chars)"]
    p = load_all().get(sid) if isinstance(sid, str) else None
    if p is None or sid not in inventory:
        return ["id: no saved profile for an installed skill with this id"]
    if content_hash != p["content_hash"] or content_hash != inventory[sid].get("content_hash"):
        return ["content_hash: the skill changed since it was profiled; re-profile it instead"]
    return save(dict(p, **{key: value}), inventory)


def _pending_tag(key: str, missing, inventory: dict) -> list[dict]:
    return [{"id": sid, "content_hash": p["content_hash"]} for sid, p in sorted(load_all().items())
            if key not in p and missing(p) and sid in inventory and p["content_hash"] == inventory[sid].get("content_hash")]


def set_domain(sid, content_hash, domain, inventory: dict) -> list[str]:
    """Add or change only the domain tag of an existing, current profile."""
    return _set_tag("domain", sid, content_hash, domain, inventory)


def pending_domains(inventory: dict) -> list[dict]:
    """Profiled skills categorized `other` that have no domain tag yet."""
    return _pending_tag("domain", lambda p: "other" in (p.get("categories") or []), inventory)


def set_focus_tag(sid, content_hash, focus_tag, inventory: dict) -> list[str]:
    """Add or change only the focus tag of an existing, current profile with no focus values."""
    return _set_tag("focus_tag", sid, content_hash, focus_tag, inventory)


def pending_focus_tags(inventory: dict) -> list[dict]:
    """Profiled skills with no focus values yet that have no focus tag either."""
    return _pending_tag("focus_tag", lambda p: not p.get("focus"), inventory)


def set_target_tag(sid, content_hash, target_tag, inventory: dict) -> list[str]:
    """Add or change only the target tag of an existing, current profile with no target values."""
    return _set_tag("target_tag", sid, content_hash, target_tag, inventory)


def pending_target_tags(inventory: dict) -> list[dict]:
    """Profiled skills with no target values yet that have no target tag either."""
    return _pending_tag("target_tag", lambda p: not p.get("targets"), inventory)


def load_all() -> dict[str, dict]:
    out = {}
    for f in sorted((paths.home() / "profiles").glob("*.json")):
        try:
            p = json.loads(f.read_text())
            # re-check the schema (minus inventory membership) so a hand-edited file cannot slip through
            if validate(p, {p["id"]: {"content_hash": p["content_hash"], "source": p["source"]}}):
                continue
            out[p["id"]] = p
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def _donor(have: dict, inventory: dict, sid: str, content_hash: str) -> dict | None:
    """An already-profiled, still-current other id with this exact content and kind: safe to clone, no
    judgment needed. Kind must match too: an agent's required multi-agent cost would be wrong for a skill
    or command that happens to share the same content hash."""
    kind = inventory.get(sid, {}).get("kind", "skill")
    for other, p in sorted(have.items()):
        if (other != sid and p.get("content_hash") == content_hash
                and other in inventory and inventory[other].get("content_hash") == p.get("content_hash")
                and inventory[other].get("kind", "skill") == kind):
            return p
    return None


def pending(inventory: dict) -> list[dict]:
    have = load_all()
    out = []
    for sid in sorted(inventory):
        rec = inventory[sid]
        prof = have.get(sid)
        if prof is not None and prof.get("content_hash") == rec.get("content_hash"):
            continue
        donor = _donor(have, inventory, sid, rec.get("content_hash"))
        if donor is not None:
            clone = dict(donor, id=sid, source=rec.get("source"), content_hash=rec.get("content_hash"))
            try:
                cloned = not save(clone, inventory)
            except OSError:
                cloned = False
            if cloned:
                have[sid] = clone
                continue
        out.append({"id": sid, "kind": rec.get("kind", "skill"), "path": rec.get("path"),
                    "reason": "new" if prof is None else "changed"})
    return out

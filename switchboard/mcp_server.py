"""Switchboard stdio MCP server: newline-delimited JSON-RPC 2.0, standard library only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter  # noqa: E402
from datetime import date  # noqa: E402

from switchboard import choices, hygiene, profiles, report, route, scan_claude, usage  # noqa: E402

VERSION = "0.7.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first; the subset this server speaks
OBJ = {"type": "object"}
STRS = {"type": "array", "items": {"type": "string"}}
TASK = {"type": "object", "description": "Structured task: category (required), targets, focus, stack, depth, cost, summary.",
        "properties": {"category": {"type": "string", "enum": list(profiles.CATEGORIES)},
                       "targets": {"type": "array", "items": {"type": "string", "enum": list(profiles.TARGETS)}},
                       "focus": {"type": "array", "items": {"type": "string", "enum": list(profiles.FOCUS)}},
                       "stack": STRS, "depth": {"type": "string", "enum": list(profiles.DEPTHS)},
                       "cost": {"type": "string", "enum": list(profiles.COSTS)},
                       "role": {"type": "string", "enum": list(profiles.ROLES),
                                "description": "performs (default): do the task; assists: work around it; meta: manage skills/settings"},
                       "summary": {"type": "string", "description": "One line; never stored."}},
        "required": ["category"]}


PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": 1000}, "offset": {"type": "integer", "minimum": 0}}


def page(items: list, args: dict, default: int, enrich=dict) -> dict:
    """One page of `items`, with `next_offset` while more remain (pages keep each result small); `enrich` runs on
    that page only."""
    limit = max(1, min(int(args.get("limit") or default), 1000))
    start = max(0, int(args.get("offset") or 0))
    out = {"total": len(items), "pending": [enrich(p) for p in items[start:start + limit]]}
    if start + limit < len(items):
        out["next_offset"] = start + limit
    return out


def schema(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required)}


TOOLS = [
    {"name": "route", "description": "Rank installed skills, commands and agents that fit a task. Returns up to 10 candidates (fewer when needed to keep the result small) with kind, how to invoke each, what each does, best_for/not_for and past choices (tie-break only), and a `next` step.",
     "inputSchema": schema({"task": TASK}, ["task"])},
    {"name": "record_choice", "description": "Record which skill the user picked (task features and ids only).",
     "inputSchema": schema({"task": TASK, "offered": STRS, "chosen": {"type": "string"}}, ["task", "offered", "chosen"])},
    {"name": "pending_profiles", "description": "Skills, commands and agents with no profile or a stale one, with paths to read. Pages: pass `offset` (from `next_offset`) for the next page.",
     "inputSchema": schema(PAGE)},
    {"name": "save_profile", "description": "Validate and save one skill profile.",
     "inputSchema": schema({"profile": OBJ}, ["profile"])},
    {"name": "pending_roles", "description": "Profiled skills with no role yet, with name and description to judge it. Pages: pass `offset` (from `next_offset`) for the next page.",
     "inputSchema": schema(PAGE)},
    {"name": "set_role", "description": "Set only the role of a current profile.",
     "inputSchema": schema({"id": {"type": "string"}, "content_hash": {"type": "string"},
                            "role": {"type": "string", "enum": list(profiles.ROLES)}}, ["id", "content_hash", "role"])},
    {"name": "pending_domains", "description": "Profiled skills categorized `other` with no domain tag yet, with "
                    "name and description to judge one. Pages: pass `offset` (from `next_offset`) for the next page.",
     "inputSchema": schema(PAGE)},
    {"name": "set_domain", "description": "Set a free-text domain tag on a current profile categorized `other`, "
                    "so similar skills can later be grouped into a new category.",
     "inputSchema": schema({"id": {"type": "string"}, "content_hash": {"type": "string"},
                            "domain": {"type": "string", "description": "A lowercase tag, e.g. video-editing, "
                                      "browser-automation (a-z0-9.+#- only, at most 40 chars)"}},
                           ["id", "content_hash", "domain"])},
    {"name": "pending_focus_tags", "description": "Profiled skills with no `focus` values and no focus tag yet, "
                    "with name and description to judge one. Pages: pass `offset` for the next page.",
     "inputSchema": schema(PAGE)},
    {"name": "set_focus_tag", "description": "Set a free-text focus tag on a current profile whose `focus` list "
                    "is empty, naming the aspect it actually cares about when none of the fixed focus values fit.",
     "inputSchema": schema({"id": {"type": "string"}, "content_hash": {"type": "string"},
                            "focus_tag": {"type": "string", "description": "A lowercase tag (a-z0-9.+#- only, "
                                         "at most 40 chars)"}},
                           ["id", "content_hash", "focus_tag"])},
    {"name": "pending_target_tags", "description": "Profiled skills with no `targets` values and no target tag "
                    "yet, with name and description to judge one. Pages: pass `offset` for the next page.",
     "inputSchema": schema(PAGE)},
    {"name": "set_target_tag", "description": "Set a free-text target tag on a current profile whose `targets` "
                    "list is empty, naming what it actually operates on when none of the fixed target values fit.",
     "inputSchema": schema({"id": {"type": "string"}, "content_hash": {"type": "string"},
                            "target_tag": {"type": "string", "description": "A lowercase tag (a-z0-9.+#- only, "
                                          "at most 40 chars)"}},
                           ["id", "content_hash", "target_tag"])},
    {"name": "status", "description": "Counts of skills, profiles, pending and overlapping categories.", "inputSchema": schema()},
    {"name": "audit", "description": "Task types where the user keeps passing over the top pick.", "inputSchema": schema()},
    {"name": "forget", "description": "Delete the local choice log. Pass confirm: true only after the user agreed.",
     "inputSchema": schema({"confirm": {"type": "boolean"}}, ["confirm"])},
    {"name": "report", "description": "Write a local HTML activity report to ~/.switchboard/report.html and return its path.",
     "inputSchema": schema()},
    {"name": "hygiene", "description": "Suggest unused plugins and user/project skills to disable, with estimated context-token savings. Read-only.",
     "inputSchema": schema({"days": {"type": "integer", "minimum": hygiene.MIN_DAYS, "maximum": hygiene.MAX_DAYS}})},
    {"name": "report_native_skills",
     "description": "Report skills from this session's own skill listing that have no plugin prefix (Claude Code's "
                    "built-ins among them: they ship inside the app, with no file for a disk scan to find). Pass "
                    "every such entry's name and description; one already backed by a file is dropped, so this is "
                    "safe to call with the full unprefixed list every time.",
     "inputSchema": schema({"skills": {"type": "array", "maxItems": scan_claude.NATIVE_MAX,
                                       "items": schema({"name": {"type": "string"}, "description": {"type": "string"}},
                                                       ["name", "description"])}}, ["skills"])},
]


inventory = scan_claude.current


def hygiene_report(days=hygiene.DEFAULT_DAYS):
    return hygiene.suggest(inventory(), usage.rows(), usage.first_seen(), date.today().isoformat(), days,
                           usage.recording_on(), scan_claude.current_mcp())


def hygiene_status(h: dict):
    if h.get("recording") is False:
        return "off"
    if h["collecting"]:
        return f"collecting {h['days_logged']}/{h['window_days']}"
    return len(h["plugins"]) + len(h["skills"])


def call_tool(name: str, args: dict):
    if name == "route":
        task = args.get("task") or {}
        return route.route(task, profiles.load_all(), inventory(), choices.similar(task))
    if name == "record_choice":
        known = set(inventory())
        chosen = args.get("chosen")
        if isinstance(chosen, str) and chosen not in known:  # a bare skill name maps to its id when unambiguous
            matches = [sid for sid in known if sid.rsplit(":", 1)[-1] == chosen]
            chosen = matches[0] if len(matches) == 1 else chosen
        if chosen not in known:
            return {"recorded": False, "error": "chosen: not an installed skill id (pass the full id, e.g. user:review)"}
        choices.record(args.get("task") or {}, args.get("offered") or [], chosen, known=known)
        return {"recorded": True, "chosen": chosen}
    if name == "pending_profiles":
        inv = inventory()
        return page(profiles.pending(inv), args, 15,
                    lambda p: dict(p, source=inv[p["id"]]["source"], content_hash=inv[p["id"]]["content_hash"],
                                   description=inv[p["id"]].get("description")))
    if name == "report_native_skills":
        return {"recorded": scan_claude.report_native(args.get("skills"))}
    if name == "save_profile":
        errs = profiles.save(args.get("profile"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "pending_roles":
        inv = inventory()
        return page(profiles.pending_roles(inv), args, 10,
                    lambda p: dict(p, name=inv[p["id"]].get("name"), description=inv[p["id"]].get("description")))
    if name == "set_role":
        errs = profiles.set_role(args.get("id"), args.get("content_hash"), args.get("role"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "pending_domains":
        inv = inventory()
        pend = [dict(p, name=inv[p["id"]].get("name"), description=inv[p["id"]].get("description"))
                for p in profiles.pending_domains(inv)]
        return page(pend, args, 10)
    if name == "set_domain":
        errs = profiles.set_domain(args.get("id"), args.get("content_hash"), args.get("domain"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "pending_focus_tags":
        inv = inventory()
        pend = [dict(p, name=inv[p["id"]].get("name"), description=inv[p["id"]].get("description"))
                for p in profiles.pending_focus_tags(inv)]
        return page(pend, args, 10)
    if name == "set_focus_tag":
        errs = profiles.set_focus_tag(args.get("id"), args.get("content_hash"), args.get("focus_tag"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "pending_target_tags":
        inv = inventory()
        pend = [dict(p, name=inv[p["id"]].get("name"), description=inv[p["id"]].get("description"))
                for p in profiles.pending_target_tags(inv)]
        return page(pend, args, 10)
    if name == "set_target_tag":
        errs = profiles.set_target_tag(args.get("id"), args.get("content_hash"), args.get("target_tag"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "status":
        inv, profs = inventory(), profiles.load_all()
        return {"skills": len(inv), "by_kind": dict(Counter(r.get("kind", "skill") for r in inv.values())),
                "profiled": sum(1 for s in profs if s in inv),
                "missing_role": len(profiles.pending_roles(inv)), "missing_domain": len(profiles.pending_domains(inv)),
                "missing_focus_tag": len(profiles.pending_focus_tags(inv)),
                "missing_target_tag": len(profiles.pending_target_tags(inv)),
                "pending": len(profiles.pending(inv)), "overlap_categories": route.overlap_categories(profs, inv),
                "hygiene": hygiene_status(hygiene_report())}
    if name == "hygiene":
        return hygiene_report(args.get("days", hygiene.DEFAULT_DAYS))
    if name == "audit":
        return {"groups": choices.audit()}
    if name == "forget":
        if args.get("confirm") is not True:  # deleting the log needs an explicit yes from the user
            return {"removed": 0, "error": "confirm: ask the user first, then call again with confirm: true"}
        return {"removed": choices.forget(), "usage_removed": usage.forget()}
    if name == "report":
        inv, profs = inventory(), profiles.load_all()
        path = report.write(inv, profs, scan_claude.current_mcp())
        return {"path": str(path), "skills": len(inv), "picks": report.summarise(inv, profs, choices.rows())["picks"]}
    raise LookupError(f"unknown tool: {name}")


def result(payload, is_error=False):
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": is_error}


def handle(msg: dict):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "switchboard", "version": VERSION}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            return result(call_tool(params.get("name"), params.get("arguments") or {}))
        except Exception as e:  # tool failures are results, not protocol errors
            return result({"error": f"{type(e).__name__}: {e}"}, True)
    raise NotImplementedError(method)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict):
                raise ValueError("not an object")
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if "id" not in msg:  # notification: no reply
                continue
            try:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
            except NotImplementedError:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "Method not found"}}
            except Exception as e:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

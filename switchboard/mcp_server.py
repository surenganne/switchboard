"""Switchboard stdio MCP server: newline-delimited JSON-RPC 2.0, standard library only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date  # noqa: E402

from switchboard import choices, hygiene, profiles, report, route, scan_claude, usage  # noqa: E402

VERSION = "0.4.0"
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


def schema(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required)}


TOOLS = [
    {"name": "route", "description": "Rank installed skills that fit a task. Returns up to 5 candidates with profiles and past choices (labels only).",
     "inputSchema": schema({"task": TASK}, ["task"])},
    {"name": "record_choice", "description": "Record which skill the user picked (task features and ids only).",
     "inputSchema": schema({"task": TASK, "offered": STRS, "chosen": {"type": "string"}}, ["task", "offered", "chosen"])},
    {"name": "pending_profiles", "description": "Skills with no profile or a stale one, with paths to read.",
     "inputSchema": schema({"limit": {"type": "integer", "minimum": 1, "maximum": 1000}})},
    {"name": "save_profile", "description": "Validate and save one skill profile.",
     "inputSchema": schema({"profile": OBJ}, ["profile"])},
    {"name": "pending_roles", "description": "Profiled skills with no role yet, with name and description to judge it.",
     "inputSchema": schema({"limit": {"type": "integer", "minimum": 1, "maximum": 1000}})},
    {"name": "set_role", "description": "Set only the role of a current profile.",
     "inputSchema": schema({"id": {"type": "string"}, "content_hash": {"type": "string"},
                            "role": {"type": "string", "enum": list(profiles.ROLES)}}, ["id", "content_hash", "role"])},
    {"name": "status", "description": "Counts of skills, profiles, pending and overlapping categories.", "inputSchema": schema()},
    {"name": "audit", "description": "Task types where the user keeps passing over the top pick.", "inputSchema": schema()},
    {"name": "forget", "description": "Delete the local choice log. Pass confirm: true only after the user agreed.",
     "inputSchema": schema({"confirm": {"type": "boolean"}}, ["confirm"])},
    {"name": "report", "description": "Write a local HTML activity report to ~/.switchboard/report.html and return its path.",
     "inputSchema": schema()},
    {"name": "hygiene", "description": "Suggest unused plugins and user/project skills to disable, with estimated context-token savings. Read-only.",
     "inputSchema": schema({"days": {"type": "integer", "minimum": hygiene.MIN_DAYS, "maximum": hygiene.MAX_DAYS}})},
]


inventory = scan_claude.current


def hygiene_report(days=hygiene.DEFAULT_DAYS):
    return hygiene.suggest(inventory(), usage.rows(), usage.first_seen(), date.today().isoformat(), days,
                           usage.recording_on())


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
        pend = profiles.pending(inv)
        limit = max(1, min(int(args.get("limit") or 20), 1000))
        items = [dict(p, source=inv[p["id"]]["source"], content_hash=inv[p["id"]]["content_hash"]) for p in pend[:limit]]
        return {"total": len(pend), "pending": items}
    if name == "save_profile":
        errs = profiles.save(args.get("profile"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "pending_roles":
        inv = inventory()
        pend = profiles.pending_roles(inv)
        limit = max(1, min(int(args.get("limit") or 100), 1000))
        return {"total": len(pend), "pending": [dict(p, name=inv[p["id"]].get("name"), description=inv[p["id"]].get("description"))
                                                for p in pend[:limit]]}
    if name == "set_role":
        errs = profiles.set_role(args.get("id"), args.get("content_hash"), args.get("role"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "status":
        inv, profs = inventory(), profiles.load_all()
        return {"skills": len(inv), "profiled": sum(1 for s in profs if s in inv),
                "missing_role": len(profiles.pending_roles(inv)),
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
        path = report.write(inv, profs)
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

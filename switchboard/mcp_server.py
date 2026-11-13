"""Switchboard stdio MCP server: newline-delimited JSON-RPC 2.0, standard library only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import choices, profiles, route, scan_claude  # noqa: E402

VERSION = "0.1.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first; the subset this server speaks
OBJ = {"type": "object"}
STRS = {"type": "array", "items": {"type": "string"}}
TASK = {"type": "object", "description": "Structured task: category (required), targets, focus, stack, depth, cost, summary.",
        "properties": {"category": {"type": "string", "enum": list(profiles.CATEGORIES)},
                       "targets": {"type": "array", "items": {"type": "string", "enum": list(profiles.TARGETS)}},
                       "focus": {"type": "array", "items": {"type": "string", "enum": list(profiles.FOCUS)}},
                       "stack": STRS, "depth": {"type": "string", "enum": list(profiles.DEPTHS)},
                       "cost": {"type": "string", "enum": list(profiles.COSTS)},
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
    {"name": "status", "description": "Counts of skills, profiles, pending and overlapping categories.", "inputSchema": schema()},
    {"name": "audit", "description": "Task types where the user keeps passing over the top pick.", "inputSchema": schema()},
    {"name": "forget", "description": "Delete the local choice log.", "inputSchema": schema()},
]


inventory = scan_claude.current


def call_tool(name: str, args: dict):
    if name == "route":
        task = args.get("task") or {}
        return route.route(task, profiles.load_all(), inventory(), choices.similar(task))
    if name == "record_choice":
        choices.record(args.get("task") or {}, args.get("offered") or [], args.get("chosen"), known=set(inventory()))
        return {"recorded": True}
    if name == "pending_profiles":
        inv = inventory()
        pend = profiles.pending(inv)
        limit = max(1, min(int(args.get("limit") or 20), 1000))
        items = [dict(p, source=inv[p["id"]]["source"], content_hash=inv[p["id"]]["content_hash"]) for p in pend[:limit]]
        return {"total": len(pend), "pending": items}
    if name == "save_profile":
        errs = profiles.save(args.get("profile"), inventory())
        return {"saved": not errs, "errors": errs}
    if name == "status":
        inv, profs = inventory(), profiles.load_all()
        return {"skills": len(inv), "profiled": sum(1 for s in profs if s in inv),
                "pending": len(profiles.pending(inv)), "overlap_categories": route.overlap_categories(profs, inv)}
    if name == "audit":
        return {"groups": choices.audit()}
    if name == "forget":
        return {"removed": choices.forget()}
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

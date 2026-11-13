"""PreToolUse hook on Skill: when several profiled skills fit that kind of task and `route` was not called
in the last 10 minutes, block once (per session, per 10 minutes) and ask Claude to call `route` first.
Skills the user named with /<skill> in this session are never blocked (see hook_prompt.py).
Fails open: any problem means print nothing, exit 0."""
import json
import sys
import time
from pathlib import Path

WINDOW = 600
REASON = ("Switchboard: several installed skills fit this kind of task. Call the switchboard route tool first, "
          "then offer the user the top 2–3.")

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from switchboard import paths, profiles, route, scan_claude

    def cleanup(now):
        for f in (paths.home() / "state").glob("*.json"):
            try:
                if now - f.stat().st_mtime > 86400:
                    f.unlink()
            except OSError:
                pass

    def profile_ids(skill, profs):
        if ":" in skill and skill in profs:
            return {skill}
        return {pid for pid in profs if pid == f"user:{skill}"
                or (pid.startswith("project:") and pid.split(":", 2)[-1] == skill)}

    def main():
        now = time.time()
        event = json.loads(sys.stdin.read())
        cleanup(now)
        tool, sf = event.get("tool_name", ""), paths.session_state(event["session_id"])
        state = json.loads(sf.read_text()) if sf.exists() else {}
        if tool.endswith("__route") and "switchboard" in tool:
            state["routed_at"] = now
            paths.write_private(sf, json.dumps(state))
            return
        if tool != "Skill":
            return
        skill = str((event.get("tool_input") or {}).get("skill") or "")
        if not skill or now - float(state.get("routed_at", 0)) <= WINDOW:
            return
        if skill in (state.get("named") or []):  # the user asked for this skill by name: never second-guess them
            return
        if now - float(state.get("nudged_at", 0)) <= WINDOW:  # block once, then let Claude proceed
            return
        inv = scan_claude.current()  # live scan: the shared inventory.json may belong to another project
        profs = profiles.load_all()
        overlap = set(route.overlap_categories(profs, inv))
        if not any(overlap & set(profs[pid].get("categories") or []) for pid in profile_ids(skill, profs) if pid in inv):
            return
        state["nudged_at"] = now
        paths.write_private(sf, json.dumps(state))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": REASON}}))

    main()
except Exception:
    pass
sys.exit(0)

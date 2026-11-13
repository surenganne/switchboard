"""PreToolUse hook on Skill: once per skill per 10 minutes, ask Claude to call `route` first when several
profiled skills fit that kind of task. Fails open: any problem means print nothing, exit 0."""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

WINDOW = 600
REASON = ("Switchboard: several installed skills fit this kind of task. Call the switchboard route tool first, "
          "then offer the user the top 2–3.")

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from switchboard import paths, profiles, route

    def state_file(session_id):
        sid = str(session_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sid):  # never let session_id pick a path
            sid = hashlib.sha256(sid.encode()).hexdigest()[:32]
        return paths.home() / "state" / f"{sid}.json"

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
        tool, sf = event.get("tool_name", ""), state_file(event["session_id"])
        state = json.loads(sf.read_text()) if sf.exists() else {"routed_at": 0, "nudged": {}}
        if tool.endswith("__route") and "switchboard" in tool:
            state["routed_at"] = now
            paths.write_private(sf, json.dumps(state))
            return
        if tool != "Skill":
            return
        skill = str((event.get("tool_input") or {}).get("skill") or "")
        if not skill or now - float(state.get("routed_at", 0)) <= WINDOW:
            return
        if now - float(state.get("nudged", {}).get(skill, 0)) <= WINDOW:
            return
        inv = json.loads((paths.home() / "inventory.json").read_text())["skills"]
        profs = profiles.load_all()
        overlap = set(route.overlap_categories(profs, inv))
        if not any(overlap & set(profs[pid].get("categories") or []) for pid in profile_ids(skill, profs) if pid in inv):
            return
        state.setdefault("nudged", {})[skill] = now
        paths.write_private(sf, json.dumps(state))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": REASON}}))

    main()
except Exception:
    pass
sys.exit(0)

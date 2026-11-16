"""PreToolUse hook on Skill and Agent. Agent calls are only logged for hygiene. On Skill: when several profiled skills fit that kind of task and no choice was recorded
in the last 10 minutes, block and ask Claude to route, ask the user and call `record_choice`. At most
MAX_DENIES blocks per session per 10 minutes, so an agent that cannot ask the user is never stuck.
Skills the user named with /<skill> in this session are never blocked (see hook_prompt.py).
Fails open: any problem means print nothing, exit 0."""
import json
import sys
import time
from pathlib import Path

WINDOW = 600
AGENT_TOOLS = ("Agent", "Task")  # Task: the Agent tool's name in older Claude Code versions
SKILL_KINDS = ("skill", "command")
MAX_DENIES = 2  # one before route, one after route without a recorded choice
REASON = ("Switchboard: several installed skills fit this kind of task. Call the switchboard route tool first, "
          "then offer the user the top 2–3 with AskUserQuestion and call record_choice.")
REASON_ROUTED = ("Switchboard: route was called but no choice was recorded. Offer the user the top 2–3 candidates "
                 "with AskUserQuestion and call record_choice with their pick (or with the single clear fit).")

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from switchboard import paths, profiles, route, scan_claude, usage

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
        if "switchboard" in tool and tool.endswith(("__route", "__record_choice")):
            state["routed_at" if tool.endswith("__route") else "chosen_at"] = now
            paths.write_private(sf, json.dumps(state))
            return
        if tool in AGENT_TOOLS:  # logged for hygiene, never blocked: skills start agents mid-workflow
            if usage.recording_on():
                usage.record(usage.resolve_ids([str((event.get("tool_input") or {}).get("subagent_type") or "")],
                                               kinds=("agent",)))
            return
        if tool != "Skill":
            return
        skill = str((event.get("tool_input") or {}).get("skill") or "")
        if usage.recording_on():
            usage.record(usage.resolve_ids([skill], kinds=SKILL_KINDS))
        if not skill or now - float(state.get("chosen_at", 0)) <= WINDOW:
            return
        if skill in (state.get("named") or []):  # the user asked for this skill by name: never second-guess them
            return
        denies = [t for t in state.get("denies") or [] if now - float(t) <= WINDOW]
        if len(denies) >= MAX_DENIES:
            return
        inv = scan_claude.current(hashed=False)  # live scan: the shared inventory.json may belong to another project
        profs = profiles.load_all()
        overlap = set(route.overlap_categories(profs, inv))
        if not any(overlap & set(profs[pid].get("categories") or []) for pid in profile_ids(skill, profs)
                   if inv.get(pid, {}).get("kind") in SKILL_KINDS):
            return
        state["denies"] = denies + [now]
        paths.write_private(sf, json.dumps(state))
        routed = now - float(state.get("routed_at", 0)) <= WINDOW
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": REASON_ROUTED if routed else REASON}}))

    main()
except Exception:
    pass
sys.exit(0)

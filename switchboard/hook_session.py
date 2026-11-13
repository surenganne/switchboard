"""SessionStart hook: refresh the inventory and tell Claude when to call `route`. Fails open."""
import hashlib
import json
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from switchboard import paths, profiles, route, scan_claude

    ROUTE = ("Before using a skill in one of them, call the switchboard `route` tool with a structured description "
             "of the task, then offer the top 2–3 to the user with AskUserQuestion (one option per skill, the reason "
             "in its description, a past choice as a label) and call `record_choice` after they pick. If only one "
             "fits clearly, use it and say which.")

    def message(overlap, n_pending):
        parts = []
        if overlap:
            parts.append(f"Switchboard: these task areas have several installed skills: {', '.join(overlap)}. {ROUTE}")
        if n_pending:
            parts.append(f"{'' if overlap else 'Switchboard: '}{n_pending} skills are not profiled yet; offer /switchboard:profile.")
        return " ".join(parts)

    def pending_is_news(pending) -> bool:
        """Offer profiling only when the set of unprofiled skills changed since the last offer."""
        digest = hashlib.sha256(json.dumps(sorted((p["id"], p["reason"]) for p in pending)).encode()).hexdigest()
        f = paths.home() / "last_offer.json"
        try:
            if json.loads(f.read_text()).get("pending") == digest:
                return False
        except (OSError, ValueError, AttributeError):
            pass
        paths.write_private(f, json.dumps({"pending": digest}))
        return True

    def main():
        inv = scan_claude.current()
        scan_claude.write_inventory(list(inv.values()))
        pending = profiles.pending(inv)
        n_pending = len(pending) if pending and pending_is_news(pending) else 0
        msg = message(route.overlap_categories(profiles.load_all(), inv), n_pending)
        if msg:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))

    main()
except Exception:
    pass
sys.exit(0)

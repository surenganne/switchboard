"""UserPromptSubmit hook: remember which skills the user named with /<skill> in this session, so the
PreToolUse hook never blocks a skill the user asked for. Stores the names only, never prompt text.
Prints nothing. Fails open: any problem means exit 0."""
import json
import re
import sys
from pathlib import Path

# "/cso", "/ecc:code-review": a slash at a word start, not part of a path like src/x or /Users/me/file
NAME = re.compile(r"(?<![\w/.:-])/([A-Za-z0-9][\w.-]*(?::[\w.-]+)*)(?![\w/])")
MAX_NAMES = 50

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from switchboard import paths

    def main():
        event = json.loads(sys.stdin.read())
        names = {n for n in NAME.findall(str(event.get("prompt") or "")) if len(n) <= 100}
        if not names:
            return
        sf = paths.session_state(event["session_id"])
        state = json.loads(sf.read_text()) if sf.exists() else {}
        state["named"] = sorted(set(state.get("named") or []) | names)[:MAX_NAMES]
        paths.write_private(sf, json.dumps(state))

    main()
except Exception:
    pass
sys.exit(0)

"""UserPromptSubmit hook. Two jobs:
1. Remember which skills the user named with /<skill> in this session, so the PreToolUse hook never blocks
   a skill the user asked for. Stores the names only, never prompt text.
2. When the prompt looks like work in a task area where several installed skills overlap, remind Claude
   to route and ask the user, even if it was about to do the work without a skill. On every matching
   prompt until a choice is recorded (then quiet for WINDOW), never when the user named a skill. The prompt is
   matched in memory and never stored.
Fails open: any problem means exit 0."""
import json
import re
import sys
import time
from pathlib import Path

# "/cso", "/ecc:code-review": a slash at a word start, not part of a path like src/x or /Users/me/file,
# nor a closing tag like </summary> from injected system text
NAME = re.compile(r"(?<![\w/.:<-])/([A-Za-z0-9][\w.-]*(?::[\w.-]+)*)(?![\w/])")
MAX_NAMES = 50
WINDOW = 600  # same as hook_pretool.WINDOW
# shortcut: keyword guess per task area, not a classifier; extend the words if an area is missed or noisy
AREAS = {
    "code-review": r"review\w*|pull request|\bprs?\b|diff|refactor\w*|simplif\w*|clean ?up|analy[sz]\w*|check\w*",
    "debugging": (r"debug\w*|bugs?|crash\w*|stack ?trace|not working|broken|failing|fix\w*|issues?|errors?|"
                  r"exceptions?|why (?:does|is|do|are)\b|(?:doesn|isn|don)'?t (?:work|see|show)"),
    "testing": r"tests?|testing|coverage|tdd|e2e",
    "security": r"security|secure|vulnerab\w*|owasp|pentest|threat model",
    "ui-design": r"\bui\b|\bux\b|frontend|landing page|css|layout|redesign",
    "planning": r"plan(ning)?|architect\w*|brainstorm\w*|spec\b|roadmap|implement\w*|build\w*|features?\b|design\b",
    "docs": r"docs?\b|documentation|readme|changelog",
    "git-release": r"commit|release|ship|merge|push",
    "cloud-devops": r"deploy\w*|docker|kubernetes|k8s|terraform|helm|ci/cd|pipeline|aws",
    "data": r"\bsql\b|database|etl|migration|dataset|warehouse",
}
AREA_RE = {a: re.compile(rf"\b(?:{w})", re.I) for a, w in AREAS.items()}
REMIND = ("Switchboard: this looks like {areas} work, where several installed skills or agents overlap. Before doing it "
          "yourself or calling a skill, call the switchboard route tool, offer the user the top 2–3 with "
          "AskUserQuestion and call record_choice. Skip this only if the user named a skill or said not to use "
          "one; describing the task does not count.")

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from switchboard import paths, profiles, route, scan_claude, usage

    def remind(prompt, state, now):
        # only a recorded choice quiets it: a reminder Claude ignored must not silence the next prompts
        if now - float(state.get("chosen_at", 0)) <= WINDOW:
            return None
        areas = [a for a, rx in AREA_RE.items() if rx.search(prompt)]
        if not areas:
            return None
        overlap = set(route.overlap_categories(profiles.load_all(), scan_claude.current(hashed=False)))
        areas = [a for a in areas if a in overlap]
        return REMIND.format(areas=", ".join(areas)) if areas else None

    def main():
        now = time.time()
        event = json.loads(sys.stdin.read())
        prompt = str(event.get("prompt") or "")
        names = {n for n in NAME.findall(prompt) if len(n) <= 100}
        sf = paths.session_state(event["session_id"])
        state = json.loads(sf.read_text()) if sf.exists() else {}
        msg = None if names else remind(prompt, state, now)
        if names:
            if usage.recording_on():
                usage.record(sorted(usage.resolve_ids(names)))
            state["named"] = sorted(set(state.get("named") or []) | names)[:MAX_NAMES]
            paths.write_private(sf, json.dumps(state))
        if msg:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))

    if __name__ == "__main__":  # importable so tests can check AREA_RE
        main()
except Exception:
    pass

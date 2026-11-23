# Primary Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When enabled, Switchboard routes before Claude does overlap-area work directly or starts an agent, not only before it calls a skill.

**Architecture:** A new `enforce` setting (`off` | `skills` | `primary`, default `skills` = today's behaviour). The prompt hook records which overlap areas a prompt touched (`pending`). In `primary` mode the PreToolUse hook also denies the first `Edit`/`Write`/`NotebookEdit` and `Agent`/`Task` call while `pending` is set and no choice was recorded in `WINDOW`, using the existing deny cap. `record_choice` accepts a `direct` sentinel so "no skill, do it myself" is a recorded answer that clears the gate.

**Tech Stack:** Python 3.9+ standard library, `unittest`, Claude Code hooks (`hooks/hooks.json`).

**Spec:** this conversation, building on `docs/superpowers/specs/2026-11-13-switchboard-design.md`.

## Global Constraints

- Python 3 standard library only; no network, no telemetry.
- Never store prompt text; state files hold area names and timestamps only.
- Every hook fails open: any error means print nothing, exit 0.
- Default behaviour must not change: with no setting, `enforce` is `skills`.
- `MAX_DENIES = 2` per session per `WINDOW = 600`; an agent that cannot ask the user is never stuck.
- A skill the user named with `/<skill>` is never gated.
- State and settings files stay mode 0600 (`paths.write_private`).

## Review Focus

- `~/.switchboard/settings.json` is corrupt, missing or has an unknown `enforce` value: behave as `skills`.
- The user wants to turn enforcement off: edits under `paths.home()` must never be gated, or `primary` cannot be switched off through Claude.
- Read-only tools (`Read`, `Bash`, `Grep`, `Glob`) are never gated.
- The user names a skill in the prompt: `pending` is cleared and nothing is gated.
- A prompt matching no area, or an area with no overlap, leaves `pending` empty and nothing is gated.

---

### Task 1: Enforce setting

**Files:**
- Modify: `switchboard/paths.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Produces: `paths.enforce_mode() -> str`, one of `"off"`, `"skills"`, `"primary"`.

- [ ] **Step 1: Write the failing tests** `test_enforce_mode_defaults_to_skills` (no settings file, corrupt JSON, unknown value `"loud"`, non-dict JSON all return `"skills"`) and `test_enforce_mode_reads_valid_values` (`"off"` and `"primary"` round-trip from `settings.json` under `SWITCHBOARD_HOME`).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_hooks -k enforce_mode`. Expected: FAIL, no `enforce_mode`.
- [ ] **Step 3: Implement `enforce_mode()` in `switchboard/paths.py`.** Read `settings.json`, catch `OSError`/`ValueError`, return the value only if it is in the allowed tuple.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: enforce setting (off, skills, primary)`.

### Task 2: `direct` is a recordable choice

**Files:**
- Modify: `switchboard/choices.py` (`record`, `audit_rows`), `switchboard/mcp_server.py` (`record_choice` branch, `route` result `next` text)
- Test: `tests/test_mcp.py`, `tests/test_choices.py`

**Interfaces:**
- Produces: `choices.DIRECT = "direct"`; `record_choice` with `chosen="direct"` returns `{"recorded": True, "chosen": "direct"}`.
- Consumes: `choices.record(task, offered, chosen, known)` unchanged signature.

- [ ] **Step 1: Write the failing tests** `test_record_choice_accepts_direct` (response above, and the log row has `chosen == "direct"`), and `test_audit_ignores_direct_overrides` (a `direct` row does not count as an override of the top pick).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_mcp tests.test_choices -k direct`. Expected: FAIL.
- [ ] **Step 3: Implement.** `choices.record` keeps `DIRECT` as a valid `chosen` even when `known` is given; `mcp_server` skips the installed-id check for it; extend the `route` `next` text to say to include a "No skill, do it directly" option. `audit_rows` skips rows whose `chosen == DIRECT`.
- [ ] **Step 4: Run the same command, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: record "direct" as a choice`.

### Task 3: Prompt hook records pending areas

**Files:**
- Modify: `switchboard/hook_prompt.py` (`remind`, `main`)
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes: `remind(prompt, state, now)` currently returns the reminder string or `None`.
- Produces: session state key `pending: list[str]` (area names). Set when a reminder fires, cleared (`[]`) when the prompt names a skill. Written in every enforce mode so switching mode mid-session works.

- [ ] **Step 1: Write the failing tests** `test_prompt_sets_pending_when_reminding` (`"review this PR"` with overlap sets `pending == ["code-review"]`; state holds no prompt text) and `test_prompt_named_skill_clears_pending`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_hooks -k pending`. Expected: FAIL.
- [ ] **Step 3: Implement.** Have `remind` also return the matched `areas`; `main` stores them under `state["pending"]`.
- [ ] **Step 4: Run it, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: prompt hook records pending overlap areas`.

### Task 4: Gate direct work and agents in primary mode

**Files:**
- Modify: `switchboard/hook_pretool.py`, `hooks/hooks.json`
- Test: `tests/test_hooks.py` (including the existing `test_hooks_json_matches_record_choice`)

**Interfaces:**
- Consumes: `paths.enforce_mode()` (Task 1), `state["pending"]` (Task 3), `state["chosen_at"]`, existing deny counter and `WINDOW`.
- Produces: `MUTATING = ("Edit", "Write", "NotebookEdit")`; `gate(tool: str, tool_input: dict, state: dict, now: float) -> bool`, true when the call must be denied. `hooks.json` PreToolUse matcher becomes `Skill|Agent|Task|Edit|Write|NotebookEdit|mcp__plugin_switchboard_switchboard__route|mcp__plugin_switchboard_switchboard__record_choice`.

- [ ] **Step 1: Write the failing tests:**
  - `test_primary_denies_first_edit_while_pending` (pending set, no choice: `Edit` is denied with `REASON`).
  - `test_primary_allows_edit_after_choice_or_direct` (a recorded choice, including `direct`, within `WINDOW` lets it through).
  - `test_primary_denies_agent_while_pending` (agent calls are denied; in `skills` mode they are still only logged).
  - `test_primary_gate_is_capped` (the third call in the window is allowed).
  - `test_primary_never_gates_edits_under_switchboard_home` (target `file_path` under `paths.home()`).
  - `test_skills_and_off_modes_never_gate_edits` (with `pending` set).
  - `test_primary_ignores_read_only_tools` (`Read`, `Bash`, `Grep`).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_hooks -k primary`. Expected: FAIL.
- [ ] **Step 3: Implement `gate` and call it from `main`.** Reuse the Skill branch's deny counter and output shape; resolve `file_path` before comparing with `paths.home()` so `..` cannot dodge the exemption. Update the matcher in `hooks/hooks.json`.
- [ ] **Step 4: Run the new tests, then the full suite** (`python3 -m unittest discover -s tests -t .`). Expected: PASS.
- [ ] **Step 5: Commit** `feat: primary mode gates direct edits and agents until routed`.

### Task 5: Docs and release

**Files:**
- Modify: `README.md` (How it works, Limits), the plugin version

- [ ] **Step 1:** Document the `enforce` setting and its three values, `direct`, the exemption for `~/.switchboard`, that `skills` stays the default, and the honest limits: area detection is keyword-based, `Bash` is not gated, other plugins' hooks run independently, and a second gate (for example ECC's GateGuard) means two prompts.
- [ ] **Step 2:** Bump the plugin version (CI tags the release from it); run the full suite. Expected: PASS.
- [ ] **Step 3: Commit** `docs: primary routing and enforce setting (v0.8.0)`.

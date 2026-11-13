# Skill Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log which skills are used (id + date only) and add a read-only `hygiene` report that suggests unused plugins and user/project skills to disable, with an estimated token saving.

**Architecture:** A new `switchboard/usage.py` owns the usage log and first-seen dates; the three existing hooks write to it. A new `switchboard/hygiene.py` is a pure function over inventory + usage rows + first-seen dates. `mcp_server.py` exposes it as the `hygiene` tool and adds one field to `status`.

**Tech Stack:** Python 3.9+, standard library only, `unittest` (run with `python3 -m unittest`).

**Spec:** `docs/superpowers/specs/2026-11-13-skill-hygiene-design.md`

## Global Constraints

- Standard library only; Python 3.9 compatible (CI runs 3.9).
- Usage row is exactly `{"date": "YYYY-MM-DD", "id": "<installed skill id>"}`; no other fields, never prompt text.
- Files: `~/.switchboard/usage.jsonl` and `~/.switchboard/first_seen.json`, created via `paths.write_private` (0600).
- Setting `{"record_usage": false}` in `~/.switchboard/settings.json` stops all usage writes.
- Hooks fail open: any exception → print nothing, exit 0.
- Window default 30 days, clamped to 7–365.
- Token estimate per skill: `ceil((len(name) + 1 + desc_chars) / 4) + 10`.
- Switchboard (source `switchboard`) is never suggested.
- Version 0.4.0 in both `.claude-plugin/plugin.json` and `mcp_server.VERSION`.

## Review Focus

1. **Forget must reset the window.** If `usage.jsonl` is deleted but `first_seen.json` kept, every skill would look unused at once. `forget` deletes both (Task 2, Task 5). *(My call; the spec only named `usage.jsonl`.)*
2. **Recording turned off.** With `record_usage: false`, hygiene must not suggest anything (no data ≠ unused): it returns `{"recording": false}` (Task 4).
3. **Corrupt files.** Bad lines in `usage.jsonl` or a non-dict `first_seen.json` are skipped, never crash a hook or the tool (Task 2).
4. **Uninstalled skills in the log** are ignored; only the current inventory is reported (Task 4).
5. **Window edge.** A use dated exactly `today - days` counts as used (Task 4).

---

### Task 1: Inventory fields for hygiene

**Files:**
- Modify: `switchboard/scan_claude.py` (`list_skills.add`, plugin loop)
- Test: `tests/test_scan.py`

**Interfaces:**
- Produces: each inventory record gains `desc_chars: int` (length of the untruncated description) and, for plugin skills only, `plugin_key: str` (e.g. `"plug@mkt"`). User/project records have no `plugin_key`.

- [ ] **Step 1: Write the failing test** `test_hygiene_fields` in `tests/test_scan.py`, using `build_fixture`: assert `inv["plug:beta"]["plugin_key"] == "plug@mkt"`, `"plugin_key" not in inv["user:alpha"]`, and `inv["user:alpha"]["desc_chars"] == len("User skill alpha")`. Add one skill with a 300-char description and assert `desc_chars == 300` while `len(description) == 240`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_scan -v` → FAIL (KeyError).
- [ ] **Step 3: Implement.** In `add`, compute `desc_chars` before the `[:240]` cut. Pass the plugin key into `skills_in`/`commands_in`/`add` as an optional `plugin_key=None` and set it on the record when given.
- [ ] **Step 4: Run** `python3 -m unittest` → all pass (content hashes unchanged, so profiles stay current).
- [ ] **Step 5: Commit** `feat(scan): desc_chars and plugin_key on inventory records`

### Task 2: Usage log module

**Files:**
- Create: `switchboard/usage.py`
- Test: `tests/test_usage.py`

**Interfaces:**
- Produces:
  - `resolve(name: str, inv: dict) -> str | None` — exact id if in `inv`; else `user:<name>` if in `inv`; else the single project id ending `:<name>`; else `None`.
  - `record(ids: list[str], today: str | None = None) -> None` — appends one row per id; no-op when recording is off or `ids` empty.
  - `rows() -> list[dict]` — parsed rows; skips bad lines and rows missing `date`/`id`.
  - `note_seen(ids, today: str | None = None) -> None` — adds missing ids to `first_seen.json` with `today`; leaves existing dates.
  - `first_seen() -> dict[str, str]` — `{}` on missing/corrupt/non-dict file.
  - `recording_on() -> bool` — reads `record_usage` from `settings.json`, default `True`.
  - `forget() -> int` — deletes `usage.jsonl` and `first_seen.json`, returns the number of rows removed.

- [ ] **Step 1: Write the failing tests** in `tests/test_usage.py` (same `SWITCHBOARD_HOME` temp-dir setup as `tests/test_choices.py`):
  - `test_record_row_shape`: `record(["user:a"], today="2026-11-13")` → one row equal to `{"date": "2026-11-13", "id": "user:a"}`; file mode `0o600`.
  - `test_record_off`: settings `{"record_usage": false}` → `record([...])` writes nothing.
  - `test_resolve`: with inv keys `{"user:review", "ecc:code-review", "project:ab12cd34:deploy"}`: `resolve("ecc:code-review")`→same, `resolve("review")`→`"user:review"`, `resolve("deploy")`→`"project:ab12cd34:deploy"`, `resolve("nope")`→`None`, `resolve("Users")`→`None`.
  - `test_note_seen_keeps_first_date`: `note_seen(["a"], "2026-11-01")`, then `note_seen(["a","b"], "2026-11-13")` → `{"a": "2026-11-01", "b": "2026-11-13"}`.
  - `test_corrupt_files`: garbage line in `usage.jsonl` is skipped; `first_seen.json` containing `[]` → `first_seen() == {}`.
  - `test_forget_deletes_both`: after record + note_seen, `forget()` returns 1 and both files are gone.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_usage -v` → FAIL (ImportError).
- [ ] **Step 3: Implement** following `choices.py`: create the log with `paths.write_private(log, "")` if missing, then append; `first_seen.json` rewritten with `paths.write_private`.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_usage -v` → PASS.
- [ ] **Step 5: Commit** `feat(usage): local usage log and first-seen dates`

### Task 3: Hooks write usage

**Files:**
- Modify: `switchboard/hook_pretool.py`, `switchboard/hook_prompt.py`, `switchboard/hook_session.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes: `usage.resolve`, `usage.record`, `usage.note_seen` (Task 2).
- Produces: a local helper in each hook, `cached_inventory() -> dict`, reading `paths.home() / "inventory.json"`'s `skills` (`{}` on any error). Comment: `shortcut: uses the last session's inventory, so a skill installed mid-session is logged from the next session`.

- [ ] **Step 1: Write the failing tests** in `tests/test_hooks.py` (fixture via `build_fixture` + `SWITCHBOARD_CLAUDE_HOME`, run `self.session()` first so `inventory.json` exists):
  - `test_session_notes_first_seen`: after `self.session()`, `first_seen.json` has every inventory id.
  - `test_pretool_logs_skill_call`: `self.pretool("Skill", {"skill": "alpha"})` → `usage.jsonl` has one row with id `user:alpha`; also logged when the call is allowed through because the user named it.
  - `test_pretool_drops_unknown`: `self.pretool("Skill", {"skill": "not-installed"})` → no `usage.jsonl` rows.
  - `test_prompt_logs_named`: prompt `"run /alpha on src/x and /Users/me/file"` → exactly one row, `user:alpha`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_hooks -v` → FAIL.
- [ ] **Step 3: Implement.**
  - `hook_pretool.py`: for `tool == "Skill"`, resolve and `usage.record` *before* the routed/named/nudged early returns.
  - `hook_prompt.py`: after collecting `names`, `usage.record([i for i in map(resolve) if i])`. Keep the `named` state write unchanged.
  - `hook_session.py`: after `write_inventory`, `usage.note_seen(list(inv))`. Respect `usage.recording_on()` (no first-seen writes when off).
- [ ] **Step 4: Run** `python3 -m unittest` → all pass.
- [ ] **Step 5: Commit** `feat(hooks): record skill usage (id and date only)`

### Task 4: Hygiene report

**Files:**
- Create: `switchboard/hygiene.py`
- Test: `tests/test_hygiene.py`

**Interfaces:**
- Consumes: inventory records with `name`, `source`, `path`, `desc_chars`, optional `plugin_key` (Task 1); rows / first-seen shapes (Task 2).
- Produces:
  - `tokens(rec: dict) -> int` — the Global Constraints formula (`desc_chars` falls back to `len(description)`).
  - `suggest(inv: dict, rows: list[dict], seen: dict, today: str, days: int = 30, recording: bool = True) -> dict` returning:
    - `{"recording": False}` when `recording` is false;
    - `{"collecting": True, "days_logged": n, "window_days": days}` when `seen` is empty or `today - min(seen.values()) < days`;
    - otherwise `{"collecting": False, "window_days": days, "plugins": [...], "mostly_unused": [...], "skills": [...], "tokens_now": int, "tokens_after": int}`.

Rules (from the spec):
- `window_start = today - days`; a skill is used if any row with its id has `date >= window_start`.
- Plugin (records sharing a `plugin_key`): in `plugins` when no member is used and the earliest member `first_seen <= window_start` → `{"plugin_key", "skills": n, "tokens"}`.
- In `mostly_unused` when some members are used and `used / n <= 0.2` → `{"plugin_key", "used": [ids], "skills": n, "tokens"}` (tokens = saving if the whole plugin is disabled).
- User/project records (no `plugin_key`): in `skills` when unused and `first_seen <= window_start` → `{"id", "path", "tokens"}`.
- Records with `source == "switchboard"` are never listed. Rows whose id is not in `inv` are ignored.
- `tokens_now` = sum over all `inv`; `tokens_after` = `tokens_now` minus `plugins` and `skills` tokens (not `mostly_unused`). Each list is sorted by `tokens` descending.
- `days` is clamped to 7–365; non-int → 30.

- [ ] **Step 1: Write the failing tests** in `tests/test_hygiene.py` with a small hand-built `inv` (plugin `p@m` with 2 skills, plugin `q@m` with 6 skills of which 1 is used, `user:a`, `user:new` first seen 3 days ago, `switchboard:status`), `today="2026-12-20"`:
  - `test_tokens_formula`: `tokens({"name": "abc", "desc_chars": 12}) == 14` (ceil(16/4) + 10), and `desc_chars` 13 → 15.
  - `test_collecting`: `seen` all dated `2026-12-01`, days 30 → `{"collecting": True, "days_logged": 19, "window_days": 30}`; `seen == {}` → `days_logged == 0`.
  - `test_recording_off`: `recording=False` → `{"recording": False}`.
  - `test_unused_plugin_and_skill`: `plugins` has `p@m` with `skills == 2`; `skills` has `user:a` but not `user:new`; nothing from `switchboard`.
  - `test_mostly_unused`: `q@m` appears in `mostly_unused` with `used == [that id]`, `skills == 6`, and not in `plugins`.
  - `test_window_edge`: a row dated exactly `2026-11-20` for `user:a` (days 30) → `user:a` not suggested.
  - `test_uninstalled_rows_ignored`: a row for `gone:x` changes nothing.
  - `test_tokens_after`: `tokens_after == tokens_now - sum(p["tokens"] for p in plugins) - sum(s["tokens"] for s in skills)`.
  - `test_days_clamped`: `days=1` → `window_days == 7`; `days="x"` → 30.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_hygiene -v` → FAIL (ImportError).
- [ ] **Step 3: Implement** `tokens` and `suggest` in `switchboard/hygiene.py` (dates via `datetime.date.fromisoformat`; ISO strings compare correctly but parse once for the subtraction).
- [ ] **Step 4: Run** `python3 -m unittest tests.test_hygiene -v` → PASS.
- [ ] **Step 5: Commit** `feat(hygiene): unused plugin and skill suggestions with token estimate`

### Task 5: Tool, command, status, forget, docs, version

**Files:**
- Modify: `switchboard/mcp_server.py`, `commands/forget.md`, `tests/test_mcp.py`, `tests/test_package.py`, `.claude-plugin/plugin.json`, `README.md`
- Create: `commands/hygiene.md`

**Interfaces:**
- Consumes: `hygiene.suggest`, `usage.rows`, `usage.first_seen`, `usage.recording_on`, `usage.forget`.
- Produces: MCP tool `hygiene` with input `{"days": integer, minimum 7, maximum 365}` returning `suggest(...)`; `status` gains `"hygiene"`: `len(plugins) + len(skills)` as an int, `"collecting N/<days>"`, or `"off"`; `forget` result gains `"usage_removed": int`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_mcp.py`: extend the tools-list set with `"hygiene"`; `test_hygiene_collecting` calls `hygiene` on a fresh home → `collecting` true; `status` has `"hygiene": "collecting 0/30"`; `forget` with `confirm: true` returns a `usage_removed` key.
  - `tests/test_package.py`: commands set includes `"hygiene"`; version test still passes at 0.4.0.
- [ ] **Step 2: Run** `python3 -m unittest -v` → FAIL on those tests.
- [ ] **Step 3: Implement.**
  - `mcp_server.py`: add the tool to `TOOLS` (description: "Suggest unused plugins and user/project skills to disable, with estimated context-token savings. Read-only."), the `call_tool` branch, the `status` field, and `usage.forget()` in the `forget` branch. `VERSION = "0.4.0"`.
  - `commands/hygiene.md` (frontmatter `description: Suggest unused plugins and skills to turn off, with the context tokens each would save`): call `hygiene`; if `recording` is false say usage logging is off and how to turn it on; if collecting say "N of 30 days logged, suggestions start after 30"; otherwise a short table (plugin or skill, skills count, ≈tokens), biggest first, then `mostly_unused` as an info list, then the totals line "skill list today ≈ X tokens; after these ≈ Y (estimate; skills and commands only)". Tell the user to disable with `/plugin` or by asking Claude; never disable anything itself.
  - `commands/forget.md`: say it deletes the choice log and the usage log (which also restarts the 30-day hygiene window).
  - `plugin.json` version `0.4.0`; README: add `/switchboard:hygiene` under Commands and What you'll see, add `usage.jsonl`/`first_seen.json` and `record_usage` to Privacy, update "Limits in v0.3" heading to v0.4 with "per-skill disable for plugin skills is not supported".
- [ ] **Step 4: Run** `python3 -m unittest` → all pass.
- [ ] **Step 5: Commit** `feat: /switchboard:hygiene, usage-aware status and forget (v0.4.0)`

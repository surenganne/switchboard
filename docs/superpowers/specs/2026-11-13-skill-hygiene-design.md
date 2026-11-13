# Skill hygiene: design

Date: 2026-11-13 · Status: draft for approval · Size: small feature

## Why

Every installed skill puts its name and description into every session's context, whether or not it is used.
With 550 skills installed, much of that list is never touched. Hygiene shows what is unused and how much
context turning it off would save, so the user can trim with evidence instead of guessing.

## Goals

- Record which skills are actually used, with no conversation content stored.
- Suggest what to turn off after a fixed window, with an estimated token saving for each suggestion.
- Keep Switchboard read-only towards Claude's settings: it suggests, the user (or Claude on request) acts.

## Non-goals

- No backfill from past session transcripts (they hold conversation content; Kavach360 no-auto-retention).
- No automatic disabling, and no editing of `settings.json` or plugin files.
- No session-start nudge.
- Not added to `report.html` in this version.

## Anti-goals (failure even if it works)

- Suggesting a skill as unused before there is enough history to know.
- Storing any prompt text, or any string that is not an installed skill id.
- Suggesting a per-skill disable that a plugin update silently undoes.

## Approaches considered

1. **Read-only report (picked).** A `hygiene` MCP tool and `/switchboard:hygiene` command, plus a usage log
   written by the existing hooks. Smallest trust ask; matches Switchboard's privacy-first stance.
2. **Report plus apply.** Same, but writes `enabledPlugins` after confirmation. Saves a step, but a plugin
   that edits Claude's config is a bigger trust ask; can be added later on top of option 1.
3. **Session-start nudge.** A line every session. Adds the kind of standing noise hygiene exists to remove.

The user handed the choice to Claude; option 1 was picked for the reasons above.

## Decisions

**Usage log.** `~/.switchboard/usage.jsonl`, created 0600 via `paths.write_private`, one line per use:
`{"date": "YYYY-MM-DD", "id": "<skill id>"}`. Written by:
- `hook_pretool.py` on every `Skill` call (before any early return, including the user-named and recently-routed paths);
- `hook_prompt.py` for each `/<name>` the user types (slash commands may not go through the `Skill` tool).

Only names that resolve to an installed skill id are written (resolve the way `hook_pretool.profile_ids`
does); anything else is dropped. Turned off by `{"record_usage": false}` in `~/.switchboard/settings.json`,
same pattern as `record_choices`. `/switchboard:forget` also deletes `usage.jsonl` (after the same confirmation).
Both hooks keep failing open.

**First seen.** `~/.switchboard/first_seen.json` maps skill id → date first seen in the inventory, updated
by `hook_session.py`. On first run every currently installed skill gets today's date, which doubles as the
log start date.

**Unused.** A skill is unused when it has zero log entries in the window *and* was first seen before the
window started. Skills first seen inside the window are never suggested.

**Window.** 30 days by default; the tool takes an optional `days` (7–365). Until the log is at least `days`
old, the tool returns no suggestions, only `collecting: N of 30 days`.

**Skill vs plugin.**
- Plugin skills: suggest disabling the **whole plugin** when none of its skills were used in the window.
- Plugins with some use: listed separately as "mostly unused" (used k of n, names of the used ones, saving
  if disabled) — informational, below the main suggestions.
- User and project skills: suggested **one by one**, with their path, since the user owns those files.
- Switchboard never suggests disabling itself.

**Token saving.** Estimate per skill: `ceil(len(name + " " + full description) / 4) + 10` (the +10 covers
list formatting). Summed per plugin, plus a total: "skill list today ≈ X tokens; after these suggestions ≈ Y".
Labelled as an estimate that counts skills and commands only — plugin agents, MCP tools and hooks are not
counted. Note: the scanner truncates descriptions to 240 characters, so the estimate needs the untruncated
length (add a `desc_chars` field to the inventory entry rather than storing the full text).

**Output.** The tool returns JSON (`window_days`, `collecting`, `plugins`, `mostly_unused`, `skills`,
`tokens_now`, `tokens_after`). The command renders it as a short table, biggest saving first, and tells the
user how to disable (`/plugin` → disable, or ask Claude). `status` gains `hygiene`: the suggestion count, or
`"collecting N/30"`.

**Tests.** Usage logging (installed id written, unknown name dropped, setting off), the unused rule
(grace period, window edge), plugin vs mixed vs user-skill grouping, token estimate, and the collecting state.

## Left to the builder

- Mapping a plugin `source` to its `name@marketplace` key for the disable instruction (from the installed
  plugins file `scan_claude` already reads).
- How `hook_prompt.py` resolves names to ids cheaply within its 5s timeout (cached `inventory.json` if fresh,
  else a live scan).
- Whether Claude Code supports hiding a single plugin skill. If it does, per-skill plugin suggestions can be
  a follow-up; this version does not rely on it.
- Version bump (0.4.0), README and CHANGELOG entries.

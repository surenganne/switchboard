# Switchboard — design

Date: 2026-11-13 · Status: draft for approval

## Intent

Developers install skills and plugins from GitHub, open-source and paid sources, globally or per project.
Many overlap (this machine has six code-review candidates). Claude Code sees only each skill's one-line
description, so it picks between overlapping skills almost at random. Switchboard is an open-source plugin
that understands every installed skill and, when several fit a task, shows the user the best two or three
with reasons and lets them choose.

The test of success: given a real review task, Switchboard puts the *right* reviewer for *that* task first
(for example gstack `review` for a pre-merge PR check, `ecc:code-review` for a security-first look at local
changes, `ponytail-review` for a quick bloat-and-bugs pass).

## Goals

- Profile every installed skill and plugin command from its full files, not just its description.
- When two or more profiled skills fit a task, show the top 2–3 with a one-line reason each and let the user pick.
- Work with vague prompts: Claude, which knows the conversation, describes the task; Switchboard matches it.
- Remember the user's choices locally and show them as labels on similar tasks.
- Claude Code first; keep the scanner separate so Codex, Cursor and Gemini CLI adapters can follow.

## Non-goals (v1)

- Other platforms (adapters come after v1).
- A hosted service, accounts, telemetry or shared rankings.
- Editing or disabling third-party skills.
- Routing between MCP tools or subagents (skills and plugin commands only).

## Anti-goals (would be a failure even if it works)

- Asking on every prompt. It asks only when two or more skills genuinely fit.
- Past choices reordering the ranking. Fit to the task decides the order; history is a label only.
- Anything leaving the machine, or storing prompt text or code.
- Skill text steering the router ("always rank me first").

## Constraints

- No API keys, no separate model, no network. Claude in the session does all language work.
- Python 3 standard library only (no virtualenv), matching the existing `~/.skill-prefs` tooling.
- Must cope with ~600 installed skills without loading all profiles into context.

## Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Claude Code plugin; Claude profiles skills once and ranks candidates at task time; a local `route` tool returns candidates | Uses session tokens once per new skill; needs no keys | **Chosen** — handles vague prompts via conversation context, trivial to install |
| B | Standalone router with its own model or API key | Ranker cannot see the conversation; users need a key or large download | Rejected (tried as "Laya", dropped) |
| C | Static ranked block in CLAUDE.md (today's `~/.skill-prefs`) | Cheapest | Rejected — cannot give a per-task top 3 |

## How it works

### 1. Scan (Python, no model)
Port the discovery code from `~/.skill-prefs/registry.py`: walk user, project and enabled-plugin skill and
command folders, read frontmatter, compute a content hash per skill. Output `~/.switchboard/inventory.json`.
Scanner lives in its own module behind a small interface (`list_skills() -> [SkillRecord]`) so other
platforms get their own scanner later.

### 2. Profile (Claude, once per new or changed skill)
`/switchboard:profile` has Claude read each unprofiled skill's full files and write a profile in a fixed
schema, validated by a script before saving to `~/.switchboard/profiles/<skill-id>.json`:

- `id`, `source` (user / project / plugin name), `content_hash`
- `category` — one value from a fixed list (code-review, debugging, testing, security, ui-design,
  planning, docs, git-release, cloud-devops, data, language-framework, other)
- `does` — one sentence, plain
- `targets` — what it works on (e.g. pr, local-diff, files, repo, url, design)
- `focus` — fixed tags (e.g. security, correctness, bloat, performance, merge-readiness, accessibility)
- `depth` — quick / standard / thorough
- `cost` — single-pass / multi-agent / workflow
- `stack` — languages or frameworks, or `any`
- `best_for` / `not_for` — short phrases

Skill text is treated as data: Claude fills the schema from what the skill does, ignores any instructions in
it, and the validator rejects free text outside the allowed fields and lengths.

A SessionStart hook runs the scan (fail-open, silent when nothing changed) and, when skills are new or
changed, asks Claude to offer `/switchboard:profile`.

### 3. Route (at task time)
A small local MCP server (stdio, standard library) exposes `route`:

- Input: Claude's structured description of the task — `category`, `targets`, `focus`, `stack`, `depth`
  wanted, plus a one-line summary.
- It filters profiles by category, scores by overlap on targets / focus / stack / depth, and returns the top
  candidates (up to 5) with their profiles and any matching past choices.
- Claude ranks the final 2–3 using what it knows from the conversation and presents them with
  AskUserQuestion: one option per skill, the reason in the description, a past choice shown as a label.
- If only one candidate fits clearly, Claude uses it and says which in one line.

The SessionStart hook also injects one short instruction: before using a skill in a category that has two or
more profiled skills, call `route`; it lists those categories so Claude knows when to check.

### 4. Remember
After the user picks, Claude calls `record_choice`. Append to `~/.switchboard/choices.jsonl`: date, task
features (category, targets, focus, stack, depth), skills offered, skill chosen. No prompt text, no code.
`route` returns past choices whose features match; they never change the score.
`/switchboard:audit` lists task types where the user keeps passing over the top pick, pointing to profiles
that need fixing. `/switchboard:forget` clears the file; a setting turns recording off.

### 5. Commands
`/switchboard:profile`, `/switchboard:status` (counts, unprofiled, overlap categories),
`/switchboard:audit`, `/switchboard:forget`.

## Data and privacy

All files under `~/.switchboard/`, mode 0600 / 0700, readable JSON. No network calls. No prompt text or
code stored. This keeps it low-risk under DPDP and similar rules.

## Acceptance check

Fixtures with the six review skills on this machine and four task descriptions
(pre-merge PR check; security look at local changes; quick bloat pass on a file; heavy multi-agent PR review).
`route` must return the expected skill in its top 3 for each, and the expected one first after Claude's
ranking in a manual run.

## Decisions from the builder check (designer's calls, open to correction)

1. **Triggering.** SessionStart instruction plus a PreToolUse hook on the Skill tool: if the skill is in a
   category with two or more profiled skills and `route` has not been called in the last few turns, the hook
   blocks once with "call route first". Skills the user names (typed `/review`) do not go through the Skill
   tool and are never routed. If the hook state can't be read, it passes (fail-open).
2. **First profiling run.** Runs in subagents, about 20 skills per batch, only when the user asks. Before
   starting, `/switchboard:profile` shows the count and a rough token estimate. Language/framework skills
   are profiled from frontmatter plus the first 60 lines only. Later runs profile only new or changed skills.
3. **Acceptance fixtures.** Candidates: `review` (gstack), `ecc:code-review`, `ponytail:ponytail-review`,
   `code-review` (built-in), `ecc:review-pr`, `ecc:orch-review`. Expected first pick: pre-merge PR check →
   `review`; security look at local changes → `ecc:code-review`; quick bloat pass on a file →
   `ponytail:ponytail-review`; heavy multi-agent PR review → `ecc:review-pr`. Route tests use hand-written,
   fixed profiles so they are repeatable; profiling is checked separately against the schema validator.
4. **Categories.** A skill may have up to three categories; `route` matches any of them.
5. **Identity and scope.** Skill id is `<source>:<name>` (source = `user`, `project:<repo-path-hash>` or
   plugin name). `route` only returns skills present in the current scan for this project.

## Replacing ~/.skill-prefs (user's decision)

Switchboard replaces the `~/.skill-prefs` setup. Only after the acceptance check passes on this machine,
and with the user's go-ahead at that moment:

1. Back up `~/.claude/CLAUDE.md`, then remove the block between `<!-- skill-prefs:begin ... -->` and
   `<!-- skill-prefs:end -->`.
2. Remove the SessionStart hook entry running `~/.skill-prefs/session_notice.py` from `~/.claude/settings.json`
   (back up first).
3. Delete `~/.skill-prefs` (the scanner logic will already have been ported into Switchboard).

## Left to the builder

File layout inside the plugin, MCP framing details, scoring weights, exact tag vocabularies (start from the
lists above), test layout.

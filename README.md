# Switchboard

You install skills and plugins from many places, and plenty of them overlap: five code reviewers, three
debuggers, a few planners. Claude Code sees only each skill's one-line description, so it picks between
overlapping skills almost at random.

Switchboard profiles every installed skill from its full files. When two or more of them fit the task in
front of you, it shows you the best two or three, each with a one-line reason, and lets you pick.

- **Asks only when it matters.** If one skill clearly fits, Claude uses it and says which.
- **Fit decides the order.** Your past picks appear as labels ("you chose this last time"). They never
  change the ranking.
- **Local only.** No network, no API keys, no telemetry. Python 3 standard library.

## Install

```sh
claude plugin marketplace add surenganne/switchboard
claude plugin install switchboard@switchboard
```

To try a local checkout instead, pass its path: `claude plugin marketplace add ./switchboard`.

Restart Claude Code. Requires `python3` (3.9 or newer) on your `PATH`.

## First run

```
/switchboard:profile
```

Claude reads each skill and writes a short, fixed-format profile (category, what it works on, focus, depth,
cost, stack). It shows you the count and a rough token cost before starting, and runs in parallel
subagents. Later sessions profile only new or changed skills; the session start message tells you when
some are waiting.

## How it works

1. **Scan.** At session start, a hook lists your user, project and enabled-plugin skills and commands, and
   hashes each one.
2. **Profile.** `/switchboard:profile` has Claude fill a fixed schema per skill. A validator accepts only
   known fields, values from fixed lists and short text, so a skill's own text cannot steer the router.
3. **Route.** Before Claude uses a skill in a task area where several profiled skills overlap, it calls the
   local `route` tool with a structured description of the task. `route` scores the candidates and Claude
   offers you the top two or three. If Claude skips this step, a hook reminds it once.
4. **Remember.** Your pick is logged locally and shown as a label on similar tasks later.

Skills you invoke yourself (typing `/review`) are never routed.

## Commands

| Command | What it does |
|---|---|
| `/switchboard:profile` | Profile new or changed skills |
| `/switchboard:status` | Counts and overlapping task areas |
| `/switchboard:audit` | Task types where you keep passing over the top pick |
| `/switchboard:forget` | Delete your choice history (asks first) |

## Privacy

Everything lives in `~/.switchboard/`. Directories are mode 0700 and files 0600.

| File | Holds |
|---|---|
| `inventory.json` | Installed skill ids, names, paths, descriptions, hashes |
| `profiles/*.json` | One profile per skill |
| `choices.jsonl` | Per pick: date, task features (category, targets, focus, stack, depth, cost), skills offered, skill chosen |
| `state/` | Per-session timestamps for the reminder hook; deleted after a day |
| `last_offer.json` | A hash of the unprofiled-skill list, so you are offered profiling only when it changes |

No prompt text and no code are stored. Feature fields keep only values from the fixed lists. To stop
recording choices, create `~/.switchboard/settings.json` with `{"record_choices": false}`.

## Limits in v0.1

- Claude Code only. The scanner sits behind a small interface (`list_skills`) so other platforms can follow.
- Built-in Claude Code skills (such as `code-review` and `simplify`) have no files on disk, so they are not
  routed.
- Skills and plugin commands only; MCP tools and subagents are not routed.

## Uninstall

```sh
claude plugin uninstall switchboard@switchboard
rm -rf ~/.switchboard
```

## Development

```sh
git clone https://github.com/surenganne/switchboard.git && cd switchboard
python3 -m unittest discover -s tests -t .
```

## License

MIT

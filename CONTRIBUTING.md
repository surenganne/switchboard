# Contributing to Switchboard

Thanks for helping. Switchboard is small on purpose: Python 3 standard library only, local only, no network.

## Ground rules

- **Keep it local.** No network calls, no telemetry, no new runtime dependencies.
- **Never store prompts.** Only task features and skill ids are logged.
- **Add a test** for any new logic. Tests live in `tests/`.

## Setup

```sh
git clone https://github.com/surenganne/switchboard
cd switchboard
python3 -m unittest discover -s tests -t .
```

Try your checkout in Claude Code: `claude plugin marketplace add ./switchboard`.

## Pull requests

1. Open an issue first for anything larger than a small fix.
2. Branch from `main`, keep the change focused, and make sure the tests pass.
3. Bump the version when behaviour changes; CI tags and publishes a release from the version bump.

Look for issues labelled `good first issue` if you want somewhere to start.

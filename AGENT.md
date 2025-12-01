Notes for Codex agent
---------------------
- Always run the full test suite (`python3 -m pytest`) before and after any code changes to confirm green builds.
- Add or update unit tests for every new code path you introduce; aim for 100% coverage and no untested branches.
- If you change execution defaults (performance/accuracy knobs), add regression-style tests or fakes to cover fallbacks.
- Keep reminders in sync with the current repo state; update this doc when workflows change.

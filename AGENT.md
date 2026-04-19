Notes for Codex agent
---------------------
- Always run the full test suite (`python3 -m pytest`) before and after any code changes to confirm green builds, and refresh all automated tests (unit, integration, e2e, snapshots) whenever you touch code.
- When you change production code, update or add the matching tests in the same pass—never leave code changes without refreshed test coverage.
- If you touch the frontend UI, run `npm run lint`, `npm test`, and `npm run e2e` (regenerating Playwright snapshots with `--update-snapshots` when copy/layout changes); do this locally before handing off so we catch snapshot/selector drift.
- Add or update unit tests for every new code path you introduce; aim for 100% coverage and no untested branches.
- If you change execution defaults (performance/accuracy knobs), add regression-style tests or fakes to cover fallbacks.
- Keep reminders in sync with the current repo state; update this doc when workflows change.
- Run linting and formatting with fail-fast semantics; do not leave warnings unresolved.
- Scan for secrets before committing (e.g., detect-secrets or gitleaks) and avoid committing any `.env*` content.
- For schema changes, include migrations, seed updates, and rollback coverage; verify up/down paths locally.
- Update lockfiles and run dependency vulnerability scans when touching dependencies.
- In PRs, always capture reproduction steps plus expected vs. actual behavior for any bugfix.

## Quality Gates

- Read `.codex/quality-gates.json` before changing or validating code.
- Use `python3 .codex/scripts/quality_runner.py check:fast` as the default shared enforcement entrypoint.
- If you prefer a thin wrapper, use the repo `Makefile` target such as `make check-fast` when it exists.
- If the repository is missing a required quality-enforcement surface, create or repair it before claiming the work is done.
- Never weaken thresholds just to make checks pass.
- Treat acceptance and E2E coverage for critical flows as human-owned. You may propose additions, but do not silently redefine or shrink the canonical product flows.
- Fast blocking gates must stay green before merge: unit coverage, integration checks, architecture rules, static analysis, security scanning, and the relevant acceptance smoke path where feasible.
- Expensive gates such as full mutation testing, heavy DAST, or deep load tests may run in scheduled workflows, but you must say explicitly when a gate is not on the PR path.
- Code-to-test ratio and function-size rules are heuristics for refactoring pressure, not excuses to write fake tests or meaningless micro-functions.
- End every substantial change with a scorecard: `pass`, `fail`, `missing`, or `blocked`.

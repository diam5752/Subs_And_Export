# Contributing to gsubs

Thank you for improving gsubs. Changes must preserve the product's privacy,
billing and local-first guarantees as well as its Python, TypeScript and Java
compatibility contracts.

## Before opening an issue

- Search existing issues first.
- Never post customer videos, transcripts, credentials, cookies, payment data or
  personal information in a public issue.
- Report security and privacy problems through GitHub's private security advisory
  form linked from `SECURITY.md`.
- Reproduce defects with deterministic mock data whenever possible.

## Development setup

The supported local profile uses mock transcription and intelligence providers and
makes no paid API calls.

```bash
git clone https://github.com/diam5752/Subs_And_Export.git
cd Subs_And_Export
make install
make run
```

In another terminal:

```bash
cd frontend
npm run dev
```

See `README.md` for runtime requirements and Docker instructions. Never copy the
production environment file into a development checkout.

## Change workflow

1. Create a focused branch from the latest `main`.
2. Add or update tests alongside every behavior change. Bug fixes need a regression
   test that fails without the fix.
3. Keep API, database migration, auth, billing and media-retention contracts
   backward compatible unless the change explicitly documents a migration.
4. Run the fast checks while iterating, then the canonical full gate before merge.
5. Open a pull request using the repository template and include redacted evidence.

```bash
make check-fast
make ci
```

`make ci` is the source of truth. It runs backend and frontend tests, Java 25
checks, real local FFmpeg export tests, browser E2E, linting, type checks, dependency
audits, architecture-cycle checks and the complexity ratchet. CI also enforces
backend line coverage of at least 90% and branch coverage of at least 80%.

## Coding standards

- TypeScript is strict; avoid `ts-ignore`, class components, inline styles and
  derived state in `useEffect`.
- Python requires type hints, `ruff`, strict `mypy` and `pathlib.Path` for paths.
- Java changes use the checked-in Maven wrapper and JDK 25.
- New functions must have cyclomatic complexity at most 10 and at most 50 active
  lines. Existing hotspots may improve but may not regress.
- Do not add live provider calls to tests. Paid-provider paths must fail closed and
  preserve idempotent credit/refund behavior.

The complete repository instructions live only in the root `AGENTS.md`.

## Pull requests and releases

- Keep one coherent change per pull request.
- Do not weaken tests, coverage, security scans or branch protection to make a PR
  pass.
- UI changes need responsive evidence for signed-in and signed-out states.
- Production releases must use an exact reviewed `main` SHA and follow the backup,
  verification and rollback procedure in `deploy/hetzner/README.md`.

Merging a pull request is not proof of deployment. A release is complete only after
the deployed SHA, health checks and public behavior have been verified.

PYTHON ?= python3
QUALITY_RUNNER = $(PYTHON) .codex/scripts/quality_runner.py
ISOLATED_QUALITY_RUNNER = $(PYTHON) .codex/scripts/run_isolated_quality_gate.py

.PHONY: ci format check-contract check-fast check-format check-static check-complexity check-cognitive check-duplicates check-file-length check-quality-suppressions check-unit check-integration check-media-export check-e2e check-arch check-java check-security check-mutation check-performance check-dast check-all

ci: check-all

format:
	ruff format .
	cd frontend && npm run format

check-contract:
	$(QUALITY_RUNNER) check:contract

check-fast:
	$(QUALITY_RUNNER) check:fast

check-format:
	$(QUALITY_RUNNER) check:format

check-static:
	$(QUALITY_RUNNER) check:static

check-complexity:
	$(QUALITY_RUNNER) check:complexity

check-cognitive:
	$(QUALITY_RUNNER) check:cognitive

check-duplicates:
	$(QUALITY_RUNNER) check:duplicates

check-file-length:
	$(QUALITY_RUNNER) check:file-length

check-quality-suppressions:
	$(QUALITY_RUNNER) check:quality-suppressions

check-unit:
	$(QUALITY_RUNNER) check:unit

check-integration:
	$(QUALITY_RUNNER) check:integration

check-media-export:
	$(QUALITY_RUNNER) check:media-export

check-e2e:
	$(QUALITY_RUNNER) check:e2e

check-arch:
	$(QUALITY_RUNNER) check:arch

check-java:
	$(QUALITY_RUNNER) check:java

check-security:
	$(QUALITY_RUNNER) check:security

check-mutation:
	$(QUALITY_RUNNER) check:mutation

check-performance:
	$(QUALITY_RUNNER) check:performance

check-dast:
	$(QUALITY_RUNNER) check:dast

check-all:
	$(ISOLATED_QUALITY_RUNNER) check:all

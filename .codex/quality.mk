PYTHON ?= python3
QUALITY_RUNNER = $(PYTHON) .codex/scripts/quality_runner.py

.PHONY: check-contract check-fast check-static check-unit check-integration check-media-export check-e2e check-arch check-java check-security check-mutation check-performance check-dast check-all

check-contract:
	$(QUALITY_RUNNER) check:contract

check-fast:
	$(QUALITY_RUNNER) check:fast

check-static:
	$(QUALITY_RUNNER) check:static

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
	$(QUALITY_RUNNER) check:all

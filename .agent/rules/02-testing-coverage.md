# Testing & Quality Assurance

## Zero-Gap Policy
> [!IMPORTANT]
> **A task is incomplete until tests pass.**

1.  **Mandatory Coverage:** Every line of new or modified code MUST have a corresponding test.
    *   **Frontend:** Unit tests (Jest) + E2E (Playwright).
    *   **Backend:** Unit/Integration tests (Pytest).
2.  **Test First:** Write the test *before* or *simultaneously* with the code.
3.  **Green Build:** You must run the full suite (`npm test`, `pytest`) before declaring a task finished.
4.  **Snapshots:** If UI changes, carefully review and update Playwright snapshots.

## Critical: Tests MUST Accompany Code Changes

> [!CAUTION]
> **NEVER commit code changes without corresponding tests.**
> This is a non-negotiable requirement. If you change production code, you MUST add tests.

### Requirements

1. **Every Code Change = New/Updated Tests:**
   - If you modify a function, add tests covering the modification
   - If you add a new feature, add tests for that feature
   - If you fix a bug, add a **regression test** that would have caught the bug

2. **Regression Tests for Bug Fixes:**
   - When fixing a bug, FIRST write a test that reproduces the bug
   - The test should FAIL before the fix and PASS after
   - Label regression tests with `# REGRESSION:` comment explaining the original bug
   - Example:
     ```python
     def test_max_lines_strictly_enforced():
         """
         REGRESSION: max_lines must be strictly enforced.
         Bug: User selected 3 lines but got 4 lines displayed.
         """
         # Test that would have caught this bug
     ```

3. **Pre-Commit Checklist:**
   - [ ] Did I add tests for ALL code changes?
   - [ ] If this is a bug fix, do I have a regression test?
   - [ ] Do all tests pass (`make test-backend`, `make test-frontend`)?
   - [ ] Is code coverage maintained or improved?

4. **Why This Matters:**
   - Bugs that slip through without tests WILL recur
   - Tests document expected behavior
   - Future refactors are safer with comprehensive tests

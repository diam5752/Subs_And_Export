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

# Tech Stack & Coding Standards

## Frontend (Next.js / TypeScript)
*   **Framework:** Next.js 16 (App Router) + React 19.
*   **Styling:** TailwindCSS v4 *only*. No CSS modules, no SASS.
*   **State:** React Hook Form for inputs. URL search params for bookmarkable state.
*   **Strictness:** `noImplicitAny` is enforced. No `ts-ignore` without rigid justification.
*   **Anti-Patterns:**
    *   ❌ `useEffect` for derived state (use `useMemo` or raw derivation).
    *   ❌ Inline styles.
    *   ❌ Class components.

## Backend (Python)
*   **Runtime:** Python 3.11+.
*   **Typing:** 100% Type Hints required. Use `mypy` strict mode.
*   **Linting:** Compliant with `ruff`.
*   **Filesystem:** Use `pathlib.Path` exclusively. ❌ No `os.path.join`.
*   **Anti-Patterns:**
    *   ❌ Global variables.
    *   ❌ Mutable default arguments.
    *   ❌ Print debugging (use strict logging).

## Java / Spring Migration Surface
*   **Runtime:** Java 25, enforced by Maven (`pom.xml` requires `[25,26)`).
*   **Build:** Use the Maven wrapper (`./mvnw`) only; do not rely on a global Maven install.
*   **Testing:** Keep JUnit, Spring integration tests, ArchUnit, and Flyway migration checks green for touched Java behavior.
*   **Contracts:** Preserve existing `/auth`, `/videos`, `/history`, `/static`, and migration compatibility contracts unless the user explicitly approves a contract change.

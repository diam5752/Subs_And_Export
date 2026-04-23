# Core Architecture & Refactoring Standards

## 1. Target Architecture
The system follows a **Local-First, Hybrid Split-Stack** architecture:

*   **Frontend (`/frontend`):** Next.js 16+ (App Router), React 19, TailwindCSS v4. Acts as the primary UI/Control Plane.
*   **Backend (`/backend`):** Python 3.11+. Handles heavy lifting (AI processing, file manipulation, subtitles).
*   **Java/Spring Migration Surface (`/src/main/java`):** Java 25 + Spring Boot compatibility surface for auth, jobs, history, static-artifact serving, and repository migration contracts.
*   **Communication:** Explicit API contracts, migrations, or CLI interfaces between FE, Python backend, and Java/Spring surfaces.

## 2. Refactoring Mandate
> [!WARNING]
> **Leave Code Cleaner Than You Found It.**

If you touch a legacy file (defined as anything not matching strict guidelines):
1.  **Refactor** it to match the current architecture.
2.  **Type** it (Strict TypeScript / Python Type Hints).
3.  **Test** it (Add missing unit/integration tests; Java/Spring changes require Maven/JUnit verification).
4.  **Delete** dead code immediately. Do not comment it out.

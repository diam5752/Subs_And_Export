## 2025-02-18 - [Critical] Unprotected Admin Endpoint
**Vulnerability:** The `/videos/jobs/cleanup` endpoint allowed unauthenticated deletion of all jobs (files and database entries).
**Learning:** Endpoints added for maintenance/admin tasks often bypass standard authentication patterns used elsewhere in the API. Dependencies like `get_job_store` do not enforce security.
**Prevention:** Always verify `current_user` is required for every new mutation endpoint. For sensitive operations, enforce role-based access control or admin allowlists beyond just "logged in".

## 2025-12-13 - [High] Unprotected Registration Endpoint
**Vulnerability:** The `/auth/register` endpoint had no rate limiting, allowing a single IP to flood the database with unlimited fake accounts.
**Learning:** Rate limiting was implemented for `login` but forgotten for `register`. Rate limiters must be explicitly applied to all public resource-creation endpoints.
**Prevention:** Audit all public POST endpoints for rate limiting decorators. Use a default global rate limiter if possible, or enforcing lint rules for public endpoints.

## 2025-02-19 - [Critical] Directory Listing Enabled on Artifacts
**Vulnerability:** The static file server `/static/` was configured to list directory contents, exposing all Job IDs and filenames (including transcripts) in `backend/data/` to anyone.
**Learning:** Using generic "serve static files" handlers often defaults to enabling directory listing, which is dangerous for directories containing sensitive user artifacts with guessable or discoverable paths.
**Prevention:** Explicitly disable directory listing when mounting static file directories. Return 404 for directories to prevent enumeration.

## 2025-05-23 - [High] Path Traversal in TikTok Upload
**Vulnerability:** The `/tiktok/upload` endpoint used `startswith` to validate paths against `DATA_DIR`. This allowed access to sibling directories sharing the same prefix (e.g., `data` vs `data_leak`).
**Learning:** String-based path validation is brittle. `startswith` is insufficient for directory containment checks because it doesn't respect path separators.
**Prevention:** Always use `pathlib.Path.relative_to(base)` or check `base in path.parents` to ensure files are strictly inside the intended directory.

## 2025-05-24 - [High] Unthrottled Video Processing
**Vulnerability:** The `/videos/process` endpoint allowed unlimited concurrent processing requests per user/IP.
**Learning:** Authentication is not a substitute for rate limiting on resource-intensive endpoints (FFmpeg/ML).
**Prevention:** Apply strict rate limits (e.g., 10/min) to all endpoints that trigger background jobs or heavy computation.

## 2025-05-25 - [Medium] User Enumeration via Timing Attack
**Vulnerability:** The `authenticate_local` method returned early when a user was not found, while performing an expensive `scrypt` hash verification when the user existed (approx 60x timing difference).
**Learning:** Even with secure hashing algorithms like `scrypt`, the *absence* of execution leaks information. User enumeration allows attackers to target valid accounts.
**Prevention:** Implement constant-time verification logic that executes the same expensive operations (hashing) regardless of whether the user exists or not, using a pre-calculated dummy hash.

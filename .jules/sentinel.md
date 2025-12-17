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
## 2025-05-25 - [Medium] FFmpeg Deadlock Risk via Unconsumed Pipe
**Vulnerability:** The `_run_ffmpeg_with_subs` function configured `subprocess.Popen` with `stdout=subprocess.PIPE` but never read from it, only iterating over `stderr`. If the subprocess wrote enough data to `stdout` to fill the OS pipe buffer, it would block indefinitely (deadlock).
**Learning:** Piping output without reading it creates a hidden availability risk. Tools like FFmpeg usually write to stderr, but may write to stdout under certain conditions or versions.
**Prevention:** Always explicitly redirect unused output streams to `subprocess.DEVNULL` to ensure the buffer cannot fill up.
## 2025-06-03 - [Medium] Unbounded Input Lengths
**Vulnerability:** The `/auth` and `/videos/process` endpoints lacked input length validation, allowing Denial of Service (DoS) via excessively large payloads (e.g., 2GB context prompts or 1GB usernames) that could exhaust server memory.
**Learning:** Pydantic models default to allowing any string length unless `Field(max_length=...)` is specified. Form parameters in FastAPI are also unbounded by default.
**Prevention:** Always enforce strict `max_length` constraints on all string inputs (Pydantic `Field` or manual checks) to prevent memory exhaustion attacks.

## 2025-06-05 - [Medium] ASS Format Injection via Subtitle Color
**Vulnerability:** The `subtitle_color` input was passed directly into the ASS style header. By injecting commas (e.g., `,0,0,0,0,1`), an attacker could shift style columns, corrupting the subtitle file or potentially crashing the renderer.
**Learning:** Text-based file formats like ASS/CSV/SRT are vulnerable to delimiter injection if inputs are not sanitized, even if they aren't "executable" code.
**Prevention:** Validate all inputs against strict allowlists (e.g., regex for colors) and sanitize/escape delimiters when constructing formatted text files.

## 2025-06-08 - [Medium] Unthrottled Content Generation
**Vulnerability:** The `/videos/jobs/{job_id}/viral-metadata` and `/videos/jobs/{job_id}/export` endpoints triggered expensive operations (LLM calls and video rendering) without rate limiting, exposing the system to resource exhaustion and financial DoS.
**Learning:** Secondary endpoints that generate content or call external paid APIs are often overlooked for rate limiting compared to primary "upload" endpoints.
**Prevention:** Apply dedicated rate limiters (e.g. `limiter_content`) to all endpoints that trigger high-cost or high-latency operations, ensuring they are protected independently or share a "heavy ops" quota.

## 2025-06-15 - [High] Session Fixation (Lack of Revocation)
**Vulnerability:** The password update endpoint updated the credential in the database but failed to invalidate existing session tokens. An attacker with a stolen session could maintain access even after the victim changed their password.
**Learning:** Changing a password does not automatically expire issued tokens (JWT or Database-backed). Session state must be explicitly managed alongside credential updates.
**Prevention:** In `update_password` and similar flows (e.g., password reset), always call `session_store.revoke_all_sessions(user_id)` to force re-authentication for all clients.

## 2025-06-18 - [Medium] Incomplete Model Validation
**Vulnerability:** While primary fields like `password` were validated, secondary fields like `confirm_password` and `ExportRequest` parameters (`resolution`, `subtitle_color`) lacked `max_length` constraints, re-introducing DoS vectors.
**Learning:** Security fixes often miss "secondary" or "confirmation" fields. Pydantic's default behavior is permissive.
**Prevention:** Use a linter or explicit audit step to ensure *every* `str` field in a Pydantic model has a `max_length` constraint or `Field(...)` definition.
## 2025-06-25 - [High] Broken Availability via Shared IP Rate Limiting
**Vulnerability:** The IP-based `RateLimiter` blocked valid authenticated users on Cloud Run because all requests originated from the same Load Balancer IP (`request.client.host`). This effectively created a shared quota for all users, leading to denial of service.
**Learning:** In containerized/serverless environments (Cloud Run, K8s), relying on source IP for rate limiting is dangerous without strict `Forwarded` header processing. Authenticated endpoints should prefer User ID over IP.
**Prevention:** For authenticated routes (`/videos/process`, `/upload`), implement `AuthenticatedRateLimiter` that keys off `user.id`. Keep IP-based limiting only for public endpoints (login/register) and ensure `ProxyHeadersMiddleware` is configured if possible.

## 2025-06-25 - [Medium] Missing Input Length Limits in Nested Models
**Vulnerability:** `TranscriptionCueRequest` and `TikTokUploadRequest` lacked `max_length` constraints on string fields, allowing potential DoS via memory exhaustion or large file writes.
**Learning:** Secondary or nested Pydantic models often miss validation that is present on primary user models. `BaseModel` does not imply safety.
**Prevention:** Audit all Pydantic models, especially those used for lists or nested structures, and ensure every `str` field has a `max_length`.

## 2025-06-26 - [High] DoS via Unbounded Resolution
**Vulnerability:** The video processing endpoints accepted arbitrary resolution strings (e.g., "100000x100000") via `_parse_resolution` and `ExportRequest`, which FFmpeg would attempt to process, leading to potential server memory exhaustion (DoS).
**Learning:** Parsing utility functions often focus on format validity (regex/split) but neglect semantic bounds checks (e.g., max dimensions), assuming inputs are "reasonable".
**Prevention:** Define global maximum constants (e.g. `MAX_RESOLUTION_DIMENSION`) and enforce them strictly in all parsing/validation logic that feeds into resource-intensive subprocesses like FFmpeg.

## 2025-06-27 - [Medium] Missing Input Length Limit on Batch Request
**Vulnerability:** The `BatchDeleteRequest` accepted a list of unbounded strings (`List[str]`), allowing an attacker to send excessively large payloads (e.g., 1MB strings) that could cause memory exhaustion during parsing or validation.
**Learning:** `List[str]` in Pydantic does not automatically inherit constraints. You must use `List[Annotated[str, Field(max_length=...)]]` to constrain the items within the list.
**Prevention:** Audit all list fields in Pydantic models to ensure the contained items have explicit length constraints.

## 2025-06-29 - [Critical] Insecure Default Environment
**Vulnerability:** The application defaulted to `DEV` mode when `APP_ENV` was unset, exposing debug endpoints (e.g., `/dev/sample-job`) and potentially insecure configurations in production if the environment variable was missing.
**Learning:** Default configurations should always favor security (Fail Secure). Relying on the presence of an environment variable to *enable* security is fragile.
**Prevention:** Changed `normalize_app_env` to default to `PRODUCTION` when the environment is unspecified. Updated build and run scripts to explicitly set `APP_ENV=dev` for development environments.
## 2025-06-28 - [Medium] Missing Length Limits on Transcription Lists
**Vulnerability:** `UpdateTranscriptionRequest` and `TranscriptionCueRequest` allowed unbounded lists of cues and words respectively, enabling DoS attacks via memory exhaustion or CPU consumption during JSON parsing/validation.
**Learning:** While individual string fields were validated, `list` fields were not. Pydantic's `list[T]` does not imply a max length.
**Prevention:** Audit all Pydantic models with `list` fields and enforce `Field(max_length=...)` or custom validators to bound the number of items.

## 2025-06-30 - [Medium] Missing Input Length Limits on Form Fields
**Vulnerability:** The `/videos/process` endpoint accepted unbounded strings for `transcribe_provider`, `openai_model`, and `video_resolution` form fields. While primary fields were validated, these secondary fields could allow large payloads, potentially leading to DoS or memory exhaustion.
**Learning:** Form parameters in FastAPI (even with default values) do not automatically enforce length limits. Manual validation is required unless Pydantic models are used for the form body (which is complex with file uploads).
**Prevention:** Explicitly check `len(field) > MAX` for all `Form()` parameters in file upload endpoints.

## 2025-07-02 - [High] Dormant Password Persistence on SSO Conversion
**Vulnerability:** When a local user logged in via Google SSO (creating an account link), the original local password hash remained in the database. This allowed continued access via the local password, even though the user provider was switched to "google" (which blocks password updates), creating an unmanageable shadow credential.
**Learning:** "Provider" fields in databases are often descriptive but not enforced by the authentication logic itself unless explicitly checked. When upgrading authentication assurance (e.g. to SSO), lower-assurance credentials must be actively revoked.
**Prevention:** In account linking/upgrading flows (`upsert_google_user`), explicitly nullify conflicting credentials (`password_hash = NULL`) to enforce the new authentication source.

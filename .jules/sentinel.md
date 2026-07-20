## 2024-03-24 - Missing Timeout in Long-Running Subprocesses

**Vulnerability:**
The FFmpeg wrappers `run_ffmpeg_with_subs` and `extract_audio` relied on a non-blocking poll loop and a database-backed cancellation check (`check_cancelled`) but lacked an explicit hard timeout. If the underlying FFmpeg process hung indefinitely (e.g., due to a corrupted file or buffer deadlock) and the user did not manually cancel the job, the backend worker process would be tied up forever, leading to resource exhaustion (DoS).

**Learning:**
Even with non-blocking I/O (`select`) and periodic application-level checks, a "hanging" external process that produces no output and ignores signals can stall the calling thread indefinitely if no timeout is enforced relative to the *start time* of the operation. Relying solely on `check_cancelled` assumes the cancellation mechanism itself (DB/Network) is available and the user initiates it.

**Prevention:**
Always implement a "hard" timeout for `subprocess` operations, even when streaming output or polling.
- Calculate `timeout = max(base_timeout, expected_duration * safety_factor)`.
- In the polling loop, check `if time.monotonic() - start_time > timeout: kill()`.
- Explicitly kill the process and raise `TimeoutError`.

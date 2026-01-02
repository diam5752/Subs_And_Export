## 2024-03-24 - DoS Protection via Subprocess Timeouts
**Vulnerability:** Long-running FFmpeg subprocesses (specifically `extract_audio` and `run_ffmpeg_with_subs`) lacked explicit timeouts in their main polling loops. While `check_cancelled` provided a way to stop them if the user initiated cancellation, a stalled or hanging process (common with corrupt video files) could tie up a worker indefinitely, leading to resource exhaustion (DoS).
**Learning:** `subprocess.Popen` with a `poll()` loop gives great control (e.g., for progress bars and cancellation), but it bypasses the simple `timeout` argument available in `subprocess.run` or `communicate`. The loop *must* check the wall-clock time against a maximum duration to ensure the process eventually terminates.
**Prevention:**
1. Always calculate and pass an explicit `timeout` to long-running task functions.
2. In polling loops (using `poll()` or `select()`), check `(time.monotonic() - start_time > timeout)` and kill the process if exceeded.
3. Derive timeouts from content length where possible (e.g., `max(600, duration * 2)`) but enforce reasonable upper bounds (e.g., 1 hour for encoding).

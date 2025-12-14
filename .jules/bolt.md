# Bolt's Journal

## 2024-05-23 - SQLite Contention on Progress Updates
**Learning:** The video processing pipeline emits progress updates at a high frequency (potentially per-frame). Writing these directly to SQLite creates significant I/O overhead and contention, especially with WAL mode enabled where every connection setup has overhead.
**Action:** Always throttle progress callbacks that write to the database (e.g., max 1 update per second) to balance UI responsiveness with backend performance.

## 2024-05-24 - SQLite Contention on Cancellation Checks
**Learning:** Similar to progress updates, the cancellation check was being performed for every line of output from FFmpeg. This resulted in excessive database reads (up to hundreds per second depending on verbosity), causing contention and slowing down the processing loop.
**Action:** Throttle job status checks in tight loops (e.g., max 1 check per second) to reduce database load while maintaining acceptable responsiveness for user cancellation.

## 2024-05-24 - Optimization of FFmpeg Stderr Loop
**Learning:** FFmpeg outputs hundreds of lines per second. Regex searching every line is expensive. Using a fast string check (`if "time=" in line`) before regex provides ~25% speedup on parsing logic. Also, even if a function is throttled internally, calling it in a tight loop incurs significant overhead (function call cost).
**Action:** Always add a fast path (string check) before regex in tight loops, and throttle function calls locally in tight loops using `time.monotonic()`.

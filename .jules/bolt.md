# Bolt's Journal

## 2024-05-23 - SQLite Contention on Progress Updates
**Learning:** The video processing pipeline emits progress updates at a high frequency (potentially per-frame). Writing these directly to SQLite creates significant I/O overhead and contention, especially with WAL mode enabled where every connection setup has overhead.
**Action:** Always throttle progress callbacks that write to the database (e.g., max 1 update per second) to balance UI responsiveness with backend performance.

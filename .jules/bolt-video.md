# ⚡ Bolt-Video Journal

## 2025-05-23 - [Serverless FFmpeg Optimization]
**Problem:** Default `ultrafast` preset was producing bloated files, and unconstrained threads caused context switching on small vCPU instances. Hardcoded CRF=20 in export forced slower encoding than necessary.
**Action:**
1.  Changed default preset to `veryfast` (Better compression, acceptable speed).
2.  Added `-threads {os.cpu_count()}` to match container resources.
3.  Added `-tune film` for better visual quality.
4.  Updated Export logic to respect user's original CRF choice (or default to 23).
**Impact:** Faster exports on Serverless (due to thread tuning), smaller file sizes, and consistent quality settings.

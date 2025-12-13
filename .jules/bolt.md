# Bolt's Journal

## 2024-05-22 - Subtitle Splitting Optimization
**Learning:** `textwrap.wrap` is computationally expensive when used inside a loop to check if text fits incrementally. It re-processes the entire string each iteration, leading to O(N^2) complexity.
**Action:** Replace incremental `textwrap.wrap` calls with a simple greedy character counter O(N) when accumulating words for subtitles. This provides significant speedup (measured ~27x in micro-benchmark).

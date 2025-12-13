# Bolt's Journal

## 2024-05-22 - Subtitle Splitting Optimization
**Learning:** `textwrap.wrap` is computationally expensive when used inside a loop to check if text fits incrementally. It re-processes the entire string each iteration, leading to O(N^2) complexity.
**Action:** Replace incremental `textwrap.wrap` calls with a simple greedy character counter O(N) when accumulating words for subtitles. This provides significant speedup (measured ~27x in micro-benchmark).

## 2025-12-13 - Karaoke Renderer Layout Caching
**Learning:** `KaraokeRenderer` was recalculating text layout (iterative font resizing and text wrapping) for every single frame, even when only the active word highlighting changed. This consumed ~30% of frame rendering time (~23ms out of ~68ms for complex cues).
**Action:** Implemented caching for the layout structure and word widths, keyed by the subtitle cue index. This reduced per-frame render time significantly for complex text, improving render throughput (FPS) by ~30-50% for text-heavy segments.

## 2025-05-24 - [Subtitle Layout Caching]
**Learning:** Subtitle segmentation () is a heavy O(N) operation involving Canvas text measurement, triggered frequently by React renders or edits. Since  objects are referentially stable during unrelated updates (like progress ticks), re-calculating layout for unchanged cues is wasteful.
**Action:** Implemented a  cache. This memoizes the expensive layout result keyed by the  object and display parameters (, ). It reduces re-layout cost to O(1) for unchanged cues, significantly smoothing UI performance during edits.
## 2025-05-24 - [Subtitle Layout Caching]
**Learning:** Subtitle segmentation is a heavy O(N) operation involving Canvas text measurement, triggered frequently by React renders or edits. Since Cue objects are referentially stable during unrelated updates (like progress ticks), re-calculating layout for unchanged cues is wasteful.
**Action:** Implemented a WeakMap based cache. This memoizes the expensive layout result keyed by the Cue object and display parameters. It reduces re-layout cost to O(1) for unchanged cues, significantly smoothing UI performance during edits.

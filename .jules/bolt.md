## 2025-02-19 - [Image Optimization Wins]
**Learning:** The codebase was serving full-resolution assets (1280x1280 PNGs) for small UI elements (icons/logos at 48px-128px). This is a massive waste of bandwidth and impacts LCP.
**Action:** Always check actual rendered size vs intrinsic size of assets. Replaced `<img>` with `next/image` to leverage automatic resizing and optimization.

## 2025-12-16 - [React Render Loop Allocations]
**Learning:** Large static data structures (arrays/objects) defined inside components are recreated on every render. In high-frequency update components (like `ProcessView` with progress polling), this adds significant GC pressure and breaks downstream `React.memo` optimizations (referential equality checks fail).
**Action:** Move static data outside component or wrap in `useMemo` with empty/stable deps. Extract complex sub-renders (grids/lists) to memoized components or `useMemo` blocks to isolate them from unrelated state updates (progress).

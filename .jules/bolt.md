## 2025-02-19 - [Image Optimization Wins]
**Learning:** The codebase was serving full-resolution assets (1280x1280 PNGs) for small UI elements (icons/logos at 48px-128px). This is a massive waste of bandwidth and impacts LCP.
**Action:** Always check actual rendered size vs intrinsic size of assets. Replaced `<img>` with `next/image` to leverage automatic resizing and optimization.

## 2025-12-16 - [React Render Loop Allocations]
**Learning:** Large static data structures (arrays/objects) defined inside components are recreated on every render. In high-frequency update components (like `ProcessView` with progress polling), this adds significant GC pressure and breaks downstream `React.memo` optimizations (referential equality checks fail).
**Action:** Move static data outside component or wrap in `useMemo` with empty/stable deps. Extract complex sub-renders (grids/lists) to memoized components or `useMemo` blocks to isolate them from unrelated state updates (progress).

## 2025-02-24 - [Context Thrashing in High-Frequency Updates]
**Learning:** Consuming a large Context in child components causes them to re-render whenever *any* part of the Context changes (e.g., `currentTime` updating 60fps during playback), even if the child only uses static properties (e.g., `AVAILABLE_MODELS`). `React.memo` on the child component itself is insufficient because the Context hook hook is a hidden dependency that bypasses the memo check.
**Action:** Wrap the *return value* of the context-consuming component in `useMemo`, including only the strictly necessary bits of the context in the dependency array. This isolates the DOM generation from the context updates.

## 2025-02-27 - [Canvas Reuse & State Pollution]
**Learning:** Reusing a singleton `HTMLCanvasElement` for text measurement optimizes performance (avoids DOM creation), but `CanvasRenderingContext2D` state (like `ctx.font`) persists. If consumers rely on closure-captured configuration without resetting the shared state, they read incorrect values (state pollution).
**Action:** When optimizing with singletons, assume dirty state. Explicitly reset context properties (like `ctx.font`) inside the active closure immediately before use, or implement a lightweight state tracker (`_lastFont`) to minimize redundant assignments.

## 2025-02-28 - [N+1 Query in Batch Operations]
**Learning:** `batch_delete_jobs` was iterating through a list of IDs and performing a DB lookup (`get_job`) for each one inside the loop, creating N+1 queries and connection overhead.
**Action:** Implemented `get_jobs` in `JobStore` to fetch all validated jobs in a single `WHERE id IN (...)` query, reducing DB roundtrips from O(N) to O(1).

## 2025-05-22 - [High-Frequency React Reconciliation]
**Learning:** Components receiving high-frequency updates (e.g. video playback `currentTime` at 60Hz) re-render and generate new React Elements every frame, triggering expensive reconciliation even if the visual output is identical (e.g. staying within the same active word).
**Action:** Use `useMemo` to derive a stable "index" (e.g. active word index) and then `useMemo` the returned JSX structure dependent on that index. This skips Element creation and Reconciliation entirely for frames where the index hasn't changed.

## 2025-12-20 - [Redundant Computation in Child Components]
**Learning:** `PreviewPlayer` was re-running `resegmentCues` (expensive text measurement/wrapping) on every render, even though the parent (`ProcessContext`) had already performed this work and passed the result via props. This wasted CPU cycles on every frame update or settings change.
**Action:** Removed the redundant calculation in the child component. Ensure expensive derived state is computed once at the highest necessary level and passed down, rather than re-computed in every consumer.

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

## 2025-02-19 - [Image Optimization Wins]
**Learning:** The codebase was serving full-resolution assets (1280x1280 PNGs) for small UI elements (icons/logos at 48px-128px). This is a massive waste of bandwidth and impacts LCP.
**Action:** Always check actual rendered size vs intrinsic size of assets. Replaced `<img>` with `next/image` to leverage automatic resizing and optimization.

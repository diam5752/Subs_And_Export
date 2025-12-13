## 2025-12-13 - [Keyboard Accessibility for Divs]
**Learning:** Interactive `div` elements (like file upload zones) are invisible to keyboard users. Adding `onClick` isn't enough - they need `tabIndex="0"`, `role="button"`, and `onKeyDown` handlers for Enter/Space keys.
**Action:** Always check `div`s with `onClick` handlers. Either replace with `<button>` or add full keyboard support.

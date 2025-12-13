## 2025-12-13 - [Keyboard Accessibility for Divs]
**Learning:** Interactive `div` elements (like file upload zones) are invisible to keyboard users. Adding `onClick` isn't enough - they need `tabIndex="0"`, `role="button"`, and `onKeyDown` handlers for Enter/Space keys.
**Action:** Always check `div`s with `onClick` handlers. Either replace with `<button>` or add full keyboard support.

## 2024-05-22 - [Nested Interactive Controls in Selection Modes]
**Learning:** When turning a list item container into a clickable button for "selection mode", any nested interactive elements (like checkboxes) create valid HTML but invalid accessibility trees. Screen readers get confused by nested controls.
**Action:** If the container becomes the primary interaction (role="button"), explicitly hide nested controls (checkboxes) from AT using `aria-hidden="true"` and `tabIndex={-1}`, and manage focus solely on the container.

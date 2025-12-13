## 2025-12-13 - [Keyboard Accessibility for Divs]
**Learning:** Interactive `div` elements (like file upload zones) are invisible to keyboard users. Adding `onClick` isn't enough - they need `tabIndex="0"`, `role="button"`, and `onKeyDown` handlers for Enter/Space keys.
**Action:** Always check `div`s with `onClick` handlers. Either replace with `<button>` or add full keyboard support.

## 2025-12-14 - [Keyboard Visibility for Actions]
**Learning:** Hiding actions until hover (e.g., `opacity-0 group-hover:opacity-100`) makes them inaccessible to keyboard users.
**Action:** Pair `group-hover:opacity-100` with `group-focus-visible:opacity-100` (and ensure parent is focusable) so tabbing reveals the action.

## 2025-12-14 - [I18n Default in Tests]
**Learning:** The testing environment (Playwright) may default to a non-English locale (e.g., Greek), breaking text-based selectors.
**Action:** When testing, either force the locale in browser context options or implement robust selectors that don't rely solely on English text (or handle multiple languages).

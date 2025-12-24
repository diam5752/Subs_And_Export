## 2025-03-05 - Error Message Accessibility
**Learning:** Error messages displayed in standard `div` elements are often missed by screen reader users if they appear dynamically.
**Action:** Always wrap error messages in a container with `role="alert"` and include a visually hidden `<span className="sr-only">Error: </span>` prefix to ensure immediate announcement and context.
## 2025-02-23 - Form Control Labeling Pattern
**Learning:** Custom slider components and toggle buttons were implemented without proper label association or semantic roles (switch vs button). Using `useId()` provides a robust way to link labels to inputs even in reusable components.
**Action:** When implementing or refactoring form controls, strictly use `htmlFor`/`id` pairs for standard inputs and `aria-labelledby` for custom controls, ensuring `role="switch"` is used for toggles.

## 2025-02-24 - Custom Video Controls Accessibility
**Learning:** Custom video player controls (Play, Pause, Mute, Seek) were implemented as generic buttons/inputs without `aria-label` or state indicators (`aria-pressed`). This makes the preview feature unusable for screen reader users.
**Action:** When implementing custom media controls, always include `aria-label` (toggling between states like "Play"/"Pause") and `aria-pressed` or `aria-valuenow` for sliders to communicate current state.

## 2025-02-27 - Focus Management in Conditional Lists
**Learning:** When action buttons in list items are replaced conditionally (e.g., Delete -> Confirm/Cancel), focus is lost unless manually managed. This disorients keyboard users.
**Action:** Use `useEffect` and `refs` to programmatically move focus to the new primary action, and restore it to the triggering element when the action is cancelled.

## 2025-02-28 - Keyboard Navigation for Interactive Headers
**Learning:** Section headers that double as "jump to step" controls were implemented as clickable `div`s without `role="button"` or keyboard event handlers. This made navigation impossible for keyboard-only users.
**Action:** Always add `role="button"`, `tabIndex={0}`, and `onKeyDown` handlers (for Enter/Space) to non-button interactive elements, or prefer semantic `<button>` elements where possible.

## 2024-05-23 - Consistent Loading States
**Learning:** Using consistent spinner components instead of just text changes for loading states significantly improves perceived performance and visual polish.
**Action:** Use the shared `<Spinner />` component for all async button states to ensure consistency and accessibility (aria-busy).

## 2025-03-01 - Accessible List Item Controls
**Learning:** In list items (like transcript cues), text content often doubles as a control (e.g., "Click to seek"). Without `aria-label`, screen readers just announce the text, leaving the interactive nature ambiguous.
**Action:** Always add descriptive `aria-label`s to list item controls (e.g., "Jump to time 0:12" instead of just "0:12") to clarify the action.

## 2025-03-03 - Power User Shortcuts
**Learning:** Repetitive tasks like editing subtitles benefit immensely from keyboard shortcuts (Save/Cancel). Adding `Ctrl+Enter` support reduced friction significantly.
**Action:** Identify high-frequency "edit-save-repeat" workflows and implement `Ctrl+Enter` (Save) / `Esc` (Cancel) shortcuts, exposing them via tooltips for discovery.

## 2025-03-04 - Focus Visibility for Custom Elements
**Learning:** Custom interactive elements (like `div role="button"`) and styled buttons often have their default focus rings suppressed by resets or `outline-none`. This renders them invisible to keyboard users.
**Action:** Explicitly add `focus-visible:ring-2` (and an appropriate color) to all interactive elements, especially those with custom styling or background colors, to ensure they are discoverable via keyboard.

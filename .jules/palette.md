# Palette's Journal

## 2025-02-23 - Form Control Labeling Pattern
**Learning:** Custom slider components and toggle buttons were implemented without proper label association or semantic roles (switch vs button). Using `useId()` provides a robust way to link labels to inputs even in reusable components.
**Action:** When implementing or refactoring form controls, strictly use `htmlFor`/`id` pairs for standard inputs and `aria-labelledby` for custom controls, ensuring `role="switch"` is used for toggles.

## 2025-02-24 - Custom Video Controls Accessibility
**Learning:** Custom video player controls (Play, Pause, Mute, Seek) were implemented as generic buttons/inputs without `aria-label` or state indicators (`aria-pressed`). This makes the preview feature unusable for screen reader users.
**Action:** When implementing custom media controls, always include `aria-label` (toggling between states like "Play"/"Pause") and `aria-pressed` or `aria-valuenow` for sliders to communicate current state.

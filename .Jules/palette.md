## 2024-12-27 - Step Indicator Accessibility

**Learning:** Custom step indicators often miss the standard `aria-current="step"` attribute, forcing screen reader users to guess their progress based on text or context. Using `<nav>` with `aria-label` and `aria-current="step"` provides immediate, semantic context.

**Action:** When auditing progress bars or multi-step forms, always verify that the active step is explicitly marked with `aria-current="step"`, not just visual styles.

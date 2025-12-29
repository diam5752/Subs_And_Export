## 2025-03-05 - Accordion Accessibility Pattern
**Learning:** Collapsible sections (accordions) must have `aria-expanded` on the trigger and `aria-controls` pointing to the content ID to be fully accessible. Adding `role="button"` to non-button triggers is essential but insufficient on its own.
**Action:** When implementing accordions, always ensure the trigger has `aria-expanded` and `aria-controls`, and the content has a matching `id`.

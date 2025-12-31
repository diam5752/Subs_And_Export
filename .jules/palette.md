## 2025-03-05 - Accessible Accordion Headers
**Learning:** Collapsible sections (Accordions) were implemented using clickable `div`s without `aria-expanded` state or `aria-controls` association. This left screen reader users unaware of the content visibility state.
**Action:** When implementing accordions, always ensure the trigger has `aria-expanded` and points to the content via `aria-controls`, and the content has a matching `id`.

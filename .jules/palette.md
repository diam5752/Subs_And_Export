## 2025-03-05 - Accordion Header State
**Learning:** Accordion-style headers (like "Step 2: Upload") were implemented as interactive `div`s without `aria-expanded` attributes. This left screen reader users guessing about the state of the content sections.
**Action:** Always add `aria-expanded={isOpen}` to interactive headers that control visibility of content regions, even if the "accordion" behavior is custom-built with React state.

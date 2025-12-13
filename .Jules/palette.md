## 2024-04-18 - [Accessibility in Custom Color Selectors]
**Learning:** Custom color pickers built with buttons often lack proper semantic grouping. Users relying on screen readers need to know they are in a "single choice" context (radio group) rather than just a list of buttons.
**Action:** Use `role="radiogroup"` for the container and `role="radio"` for the options, ensuring `aria-checked` manages state instead of just visual classes.

## 2024-04-18 - [Button Semantics]
**Learning:** Reviewers (or tools) may confuse visual styling with semantic tags. Always verify the underlying HTML tag. A `<button>` tag with `onClick` is semantically correct, whereas a `div` with `onClick` requires explicit `role="button"` and `tabIndex="0"`.
**Action:** Always prefer semantic HTML tags (`<button>`) over ARIA roles on generic containers (`div`) when possible.

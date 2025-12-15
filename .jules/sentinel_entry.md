
## 2025-06-18 - [Medium] Incomplete Model Validation
**Vulnerability:** While primary fields like `password` were validated, secondary fields like `confirm_password` and `ExportRequest` parameters (`resolution`, `subtitle_color`) lacked `max_length` constraints, re-introducing DoS vectors.
**Learning:** Security fixes often miss "secondary" or "confirmation" fields. Pydantic's default behavior is permissive.
**Prevention:** Use a linter or explicit audit step to ensure *every* `str` field in a Pydantic model has a `max_length` constraint or `Field(...)` definition.

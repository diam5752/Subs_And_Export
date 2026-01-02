## 2024-05-23 - Path Traversal Prevention
**Vulnerability:** Ad-hoc path validation using `resolve().relative_to()` was duplicated across multiple files (`main.py`, `job_routes.py`), increasing the risk of inconsistent application or omission.
**Learning:** Python's `pathlib.Path.resolve().is_relative_to(base)` is the robust standard for preventing traversal attacks, but it must be applied consistently to both the target path AND the base directory to prevent symlink bypasses.
**Prevention:** Centralized the logic into a `validate_path_is_safe(path, base)` helper function in `file_utils.py` and enforced its use across all file-handling endpoints.

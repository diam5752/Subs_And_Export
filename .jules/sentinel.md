## 2024-05-23 - Path Traversal Prevention in Python
**Vulnerability:** Path traversal (e.g. `../../etc/passwd`) is a common risk when serving files or handling user-supplied identifiers mapped to filesystem paths. Ad-hoc checks like `if ".." in path` are insufficient due to normalization bypasses.
**Learning:** In Python, the only robust way to validate a path is contained within a base directory is using `pathlib.Path.resolve()` followed by `.is_relative_to(base)`. This correctly handles `..` segments, symlinks, and absolute paths in a cross-platform manner.
**Prevention:** Always use the centralized `validate_path_is_safe` utility in `backend/app/api/endpoints/file_utils.py` instead of implementing custom checks.

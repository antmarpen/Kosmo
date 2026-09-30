"""Filesystem path checks for worker-owned task storage boundaries."""

from pathlib import Path


def safe_path(assigned_directory: str | Path, name_or_path: str | Path) -> Path:
    """Return a resolved path inside an assigned directory, rejecting escapes.

    Relative names are limited to the shared logical-identifier grammar. Full
    paths are accepted only when they are already within the assigned scope.
    Existing symlink components are resolved before containment is checked.
    """
    root = Path(assigned_directory).resolve()
    value = Path(name_or_path)
    if value.is_absolute():
        candidate = value
    else:
        if not value.parts or any(part in {".", ".."} for part in value.parts):
            raise ValueError("Unsafe storage path")
        if any(not is_safe_identifier(part) for part in value.parts):
            raise ValueError("Unsafe storage path")
        candidate = root / value
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Storage path escapes assigned directory")
    return resolved


def is_safe_identifier(value: str) -> bool:
    return bool(value) and len(value) <= 64 and all(
        char.isascii() and (char.isalnum() or char in "._-") for char in value
    ) and ".." not in value

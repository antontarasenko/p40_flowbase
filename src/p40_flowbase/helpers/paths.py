"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import hashlib

_DEFAULT_MAX_BYTES = 255


def safe_path_component(name: str, max_bytes: int = _DEFAULT_MAX_BYTES) -> str:
    """Shorten a path component to fit within filesystem filename limits.

    If the UTF-8 encoding of ``name`` exceeds ``max_bytes``, the name is
    truncated and a SHA-256 hash suffix is appended so that distinct long
    names still map to distinct directory names.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    truncated = encoded[: max_bytes - 17].decode("utf-8", errors="ignore")
    return f"{truncated}_{digest}"

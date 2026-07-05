"""Tiny stdlib helpers for reporting file/directory size and counts.

Used by the centralized ``DataObject`` lifecycle logging in
``core/base.py`` and by ``Composite._make_summary``.
"""

import hashlib
import pathlib


def count_files(path: pathlib.Path) -> int:
    """Count regular files under ``path`` (recursive).

    Returns 0 if ``path`` does not exist. If ``path`` is a regular
    file, returns 1.
    """
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for p in path.rglob("*") if p.is_file())


def dir_size_bytes(path: pathlib.Path) -> int:
    """Sum the byte-size of all regular files under ``path`` (recursive).

    Returns 0 if ``path`` does not exist or is empty.
    """
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def file_or_dir_size_bytes(path: pathlib.Path) -> int:
    """Size of one file, or recursive dir size, or 0 if missing."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return dir_size_bytes(path)


def sha256_of_path(path: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of a file, or of a directory tree.

    For a directory the digest is deterministic and order-independent:
    each regular file contributes its POSIX-relative path plus its own
    digest, walked in sorted order. Lets a data consumer verify a master
    copy (file or multi-file directory) without a database.
    """
    if path.is_dir():
        tree = hashlib.sha256()
        for p in sorted(x for x in path.rglob("*") if x.is_file()):
            tree.update(p.relative_to(path).as_posix().encode())
            with p.open("rb") as fh:
                tree.update(hashlib.file_digest(fh, "sha256").digest())
        return tree.hexdigest()
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()

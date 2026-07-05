"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import (
    Any,
    ClassVar,
    override,
)

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import CompositeFormat
from p40_flowbase.dagster.wiring import DagsterAssetWiring
from p40_flowbase.helpers.file_stats import (
    count_files,
    dir_size_bytes,
)
from p40_flowbase.logging import logger


@dataclass(frozen=True)
class FileSpec:
    """One documented entry of a ``Composite.expected_files`` index.

    :ivar name: A concrete relative path (``logo.png``) or a glob pattern
        in ``pathlib`` semantics (``*.csv`` at the top level, ``**/*.csv``
        recursively; ``**`` is a whole path segment, not ``**.csv``).
        Matched against files under ``.files`` via
        :meth:`pathlib.PurePath.full_match`.
    :ivar description: What the file(s) are, for a human reader.
    """

    name: str
    description: str


def _is_glob(name: str) -> bool:
    """Whether ``name`` is a glob pattern rather than a concrete path."""
    return any(ch in name for ch in "*?[")


@dataclass(frozen=True)
class IndexCoverage:
    """Match of ``expected_files`` against the on-disk ``.files`` directory.

    :ivar per_spec: One ``(spec, matched_relative_paths)`` pair per
        ``FileSpec``, preserving declaration order.
    :ivar unindexed: POSIX-relative paths of files that no spec matched.
    """

    per_spec: tuple[tuple[FileSpec, tuple[str, ...]], ...]
    unindexed: tuple[str, ...]

    @property
    def missing_specs(self) -> tuple[FileSpec, ...]:
        """Specs that matched no file at all."""
        return tuple(spec for spec, matches in self.per_spec if not matches)


class Composite(DataObject, DagsterAssetWiring):
    """Base class for composite data objects with multiple files stored as directory.

    Composite objects store multiple files in a directory structure.
    Supported formats:
        - FILES: Directory containing files (default)
        - ZIP: Compressed zip archive
        - TAR_ZST: Tar archive with zstd compression

    :cvar expected_files: Optional documentation index describing the
        files this object is expected to hold, as ``FileSpec(name,
        description)`` entries. Need not be exhaustive: use a glob
        (``**/*.csv``) to cover a whole family in one line. Rendered
        verbatim (globs kept) in ``readme.html``; expanded to the actual
        matched filenames in ``meta.json``.
    """

    make_format: ClassVar[CompositeFormat] = CompositeFormat.FILES  # pyright: ignore[reportIncompatibleVariableOverride]
    expected_files: ClassVar[tuple[FileSpec, ...]] = ()
    readme_kind: ClassVar[str] = "composite"

    @override
    def _make_summary(self) -> dict[str, Any]:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        return {
            "files": count_files(files_dir),
            "files_bytes": dir_size_bytes(files_dir),
        }

    def _files_relative(self) -> list[str]:
        """POSIX-relative paths of every file under ``.files`` (sorted)."""
        files_dir = self.path_to_format(CompositeFormat.FILES)
        if not files_dir.is_dir():
            return []
        return sorted(
            p.relative_to(files_dir).as_posix()
            for p in files_dir.rglob("*")
            if p.is_file()
        )

    def index_coverage(self) -> IndexCoverage:
        """Match ``expected_files`` against the on-disk ``.files``.

        Single source of truth shared by the ``meta.json`` expansion and
        the coverage checks (``ck.AllExpectedFilesPresent`` /
        ``ck.NoUnindexedFiles``). Matching uses ``pathlib`` glob semantics
        via :meth:`pathlib.PurePath.full_match` (case-sensitive POSIX).
        """
        all_files = self._files_relative()
        indexed: set[str] = set()
        per_spec: list[tuple[FileSpec, tuple[str, ...]]] = []
        for spec in self.expected_files:
            matches = tuple(
                rel for rel in all_files if PurePosixPath(rel).full_match(spec.name)
            )
            indexed.update(matches)
            per_spec.append((spec, matches))
        unindexed = tuple(rel for rel in all_files if rel not in indexed)
        return IndexCoverage(per_spec=tuple(per_spec), unindexed=unindexed)

    @override
    def _readme_context(self) -> dict[str, Any]:
        """Add the file index verbatim (globs kept; no disk access)."""
        ctx = super()._readme_context()
        ctx["expected_files"] = [
            {"name": s.name, "description": s.description, "is_glob": _is_glob(s.name)}
            for s in self.expected_files
        ]
        return ctx

    @override
    def _meta_optional(self) -> dict[str, Any]:
        """Expand the file index against ``.files`` to actual filenames.

        Each spec reports the concrete files it matched; ``unindexed``
        lists on-disk files that no spec covers (informational, since the
        index need not be exhaustive).
        """
        opt = super()._meta_optional()
        cov = self.index_coverage()
        opt["expected_files"] = [
            {
                "name": spec.name,
                "description": spec.description,
                "is_glob": _is_glob(spec.name),
                "matches": list(matches),
            }
            for spec, matches in cov.per_spec
        ]
        opt["unindexed"] = list(cov.unindexed)
        return opt

    def _convert_to_zip(self) -> None:
        import zipfile

        zip_path = self.path_to_format(CompositeFormat.ZIP)
        files_path = self.path_to_format(CompositeFormat.FILES)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_path.rglob("*"):
                if file_path.is_file():
                    zipf.write(file_path, file_path.relative_to(files_path))

    def _convert_to_tar_zst(self) -> None:
        tar_zst_path = self.path_to_format(CompositeFormat.TAR_ZST)
        tar_process = subprocess.Popen(
            ["tar", "-C", str(self.local_dir), "-cf", "-", f"{self.object_stem}.files"],
            stdout=subprocess.PIPE,
        )
        zstd_process = subprocess.Popen(
            ["zstd", "-o", str(tar_zst_path)],
            stdin=tar_process.stdout,
        )
        try:
            assert tar_process.stdout is not None  # noqa: S101  # stdout=PIPE was passed
            tar_process.stdout.close()
            zstd_process.communicate()
            tar_process.wait()
        finally:
            for proc in (tar_process, zstd_process):
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        if tar_process.returncode != 0 or zstd_process.returncode != 0:
            raise subprocess.CalledProcessError(
                tar_process.returncode or zstd_process.returncode,
                "tar | zstd",
            )


class ManualComposite(Composite):
    """Composite whose ``.files`` are added by hand, never generated.

    A ``ManualComposite`` is the entry point for raw material that is
    *uploaded* rather than *built*: emails, attachments, exports, S3
    pulls. ``_make`` only ensures the empty ``.files`` directory exists,
    so the object materializes cleanly before any files land in it; the
    files themselves are copied in out-of-band and then left alone — no
    pipeline step overwrites them.

    Because the contents are hand-curated and cannot be regenerated, the
    destructive and derived paths are disabled:

    * ``make`` is idempotent and never wipes. ``replace=True`` is
      neutralized with a warning, so a global Dagster ``replace`` run
      cannot clear the uploaded files.
    * ``delete`` raises — a manual object must be removed deliberately,
      by hand.
    * ``convert`` is a no-op (with a warning), so ``.files`` stays the
      only format on disk. Side formats (``.zip``, ``.tar.zst``) are
      refused: they are snapshots, and because we never rebuild this
      object to refresh them, they would silently drift from the
      hand-edited originals.

    As a Dagster asset it is marked not rebuildable (a definition-time
    ``rebuildable=false`` tag + metadata), so a global rebuild run skips
    it and the UI flags that its data is managed out-of-band.
    """

    #: Hand-uploaded, so a global run must not recreate it; read by
    #: ``assets_from_classes`` to stamp the not-rebuildable mark.
    asset_rebuildable: ClassVar[bool] = False

    @override
    def _make(self) -> None:
        # Files are added by hand, so only ensure the directory exists.
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)

    @override
    def _check_make_preconditions(self, replace: bool) -> None:
        # Never wipe hand-curated files: neutralize replace, keep make() idempotent.
        if replace:
            logger.warning(
                f"replace_ignored | object={self.object_stem} "
                f"reason=manual files are added by hand, not regenerated"
            )
        self.local_dir.mkdir(parents=True, exist_ok=True)

    @override
    def convert(self, fmt: StrEnum | None = None, replace: bool = False) -> None:
        # Keep .files the only format (side formats would drift from
        # originals we never rebuild); neutralize, don't raise, so a
        # global convert run skips this object.
        del fmt, replace
        logger.warning(
            f"convert_ignored | object={self.object_stem} "
            f"reason=manual object keeps only .files; side formats would drift"
        )

    @override
    def delete(self) -> None:
        msg = (
            f"Refusing to delete manual object {self.object_stem}: its files "
            f"are added by hand, not generated. Remove {self.local_dir} "
            f"manually if this is intended."
        )
        raise RuntimeError(msg)

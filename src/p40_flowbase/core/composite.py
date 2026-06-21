"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import subprocess
from enum import StrEnum
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


class Composite(DataObject, DagsterAssetWiring):
    """Base class for composite data objects with multiple files stored as directory.

    Composite objects store multiple files in a directory structure.
    Supported formats:
        - FILES: Directory containing files (default)
        - ZIP: Compressed zip archive
        - TAR_ZST: Tar archive with zstd compression
    """

    make_format: ClassVar[CompositeFormat] = CompositeFormat.FILES  # pyright: ignore[reportIncompatibleVariableOverride]

    @override
    def _make_summary(self) -> dict[str, Any]:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        return {
            "files": count_files(files_dir),
            "files_bytes": dir_size_bytes(files_dir),
        }

    def _convert_to_zip(self) -> None:
        """Convert files directory to zip."""
        import zipfile

        zip_path = self.path_to_format(CompositeFormat.ZIP)
        files_path = self.path_to_format(CompositeFormat.FILES)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_path.rglob("*"):
                if file_path.is_file():
                    zipf.write(file_path, file_path.relative_to(files_path))

    def _convert_to_tar_zst(self) -> None:
        """Convert files directory to tar.zst."""
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

    #: Intrinsic: hand-uploaded, so a global run must not recreate it.
    #: Read by ``assets_from_classes`` to stamp the not-rebuildable mark.
    asset_rebuildable: ClassVar[bool] = False

    @override
    def _make(self) -> None:
        # Files are added by hand, so only ensure the directory exists.
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)

    @override
    def _check_make_preconditions(self, replace: bool) -> None:
        # Never wipe a hand-curated object: keep make() idempotent and
        # neutralize replace so it cannot delete the uploaded files.
        if replace:
            logger.warning(
                f"replace_ignored | object={self.object_stem} "
                f"reason=manual files are added by hand, not regenerated"
            )
        self.local_dir.mkdir(parents=True, exist_ok=True)

    @override
    def convert(self, fmt: StrEnum | None = None, replace: bool = False) -> None:
        # Keep .files the only format: side formats are snapshots that
        # would drift from the hand-edited originals we never rebuild.
        # Neutralize (don't raise) so a global convert run skips this
        # object instead of crashing on it.
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

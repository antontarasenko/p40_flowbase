"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import subprocess
from typing import (
    Any,
    ClassVar,
    override,
)

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import CompositeFormat
from p40_flowbase.helpers.file_stats import (
    count_files,
    dir_size_bytes,
)


class Composite(DataObject):
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

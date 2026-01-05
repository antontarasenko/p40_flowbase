"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import subprocess

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import CompositeFormat
from p40_flowbase.logging import logger


class CompositeDataObject(DataObject):
    """Base class for composite data objects with multiple files stored as directory.

    Composite objects store multiple files in a directory structure.
    Supported formats:
        - FILES: Directory containing files (default)
        - ZIP: Compressed zip archive
        - TAR_ZST: Tar archive with zstd compression
    """

    make_format: CompositeFormat = CompositeFormat.FILES

    def _convert_to_zip(self) -> None:
        """Convert files directory to zip."""
        import zipfile

        zip_path = self.path_to_format(CompositeFormat.ZIP)
        files_path = self.path_to_format(CompositeFormat.FILES)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_path.rglob("*"):
                if file_path.is_file():
                    zipf.write(file_path, file_path.relative_to(files_path))
        logger.info(f"Converted to ZIP: {zip_path}")

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
        tar_process.stdout.close()
        zstd_process.communicate()
        tar_process.wait()
        if tar_process.returncode != 0 or zstd_process.returncode != 0:
            raise subprocess.CalledProcessError(
                tar_process.returncode or zstd_process.returncode,
                "tar | zstd",
            )
        logger.info(f"Converted to TAR.ZST: {tar_zst_path}")

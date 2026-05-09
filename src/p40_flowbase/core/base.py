"""
MIT License

Copyright (c) 2025 Anton Tarasenko

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import pathlib
import shutil
import time
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Sequence
from dataclasses import dataclass
from enum import (
    Enum,
    StrEnum,
)
from typing import (
    Any,
    ClassVar,
)

from p40_flowbase.helpers.file_stats import (
    count_files,
    file_or_dir_size_bytes,
)
from p40_flowbase.logging import (
    logger,
    object_log_context,
)


@dataclass(frozen=True)
class DataObjectVersion:
    """Version metadata for data objects.

    Attributes:
        id: Short identifier for the version (e.g., "main", "v1", "test").
        name: Human-readable name for the version.
        description: Detailed description of what this version contains.
    """

    id: str
    name: str
    description: str


def format_summary(phase: str, kvs: dict[str, Any]) -> str:
    """Render a one-line summary in the project's pipe-`k=v` style.

    `path=...` is moved last (it's the longest field; trailing it keeps
    the head readable). Other key order is preserved as inserted.
    """
    path = kvs.pop("path", None)
    body = " ".join(f"{k}={v}" for k, v in kvs.items())
    if path is not None:
        body = f"{body} path={path}" if body else f"path={path}"
    return f"{phase}_summary | {body}"


class DataObject(ABC):
    """Base class for all data objects.

    Subclasses must define:
        - id: Unique identifier for the data object type.
        - description: Human-readable description.
        - make_format: Default format enum for the make() method.
        - supported_versions: Tuple of version enums.
        - _make(): Method to create the object in default format.

    Lifecycle logging
    -----------------
    Every ``make()`` / ``convert()`` / ``delete()`` call:

    1. Opens an ``object_log_context``: a per-object FileHandler at
       ``<local_dir>/<object_stem>.log`` (append mode), filtered to
       only this object's records via a ``ContextVar``. Concurrent
       ``make()`` calls do not bleed into each other's files.
    2. Writes a single-line ``<phase>_summary | k=v ... path=<abs>``
       summary at the end. Subclasses contribute fields by overriding
       ``_make_summary`` / ``_convert_summary`` / ``_delete_summary``.
    3. On failure: logs the traceback via ``logger.exception(...)``
       (so it lands in the per-object log) and re-raises.
    """

    id: ClassVar[str]
    description: ClassVar[str]
    make_format: ClassVar[StrEnum]
    supported_versions: ClassVar[tuple[Enum, ...]] = ()
    version: Enum

    # Must be set by project config
    _local_data: ClassVar[str | None] = None

    def __init__(self, version: Enum):
        """Initialize a data object with a specific version.

        Args:
            version: Version enum member from supported_versions.

        Raises:
            ValueError: If version is not in supported_versions.
        """
        if version not in self.supported_versions:
            raise ValueError(
                f"Version {version} not in supported_versions for {self.__class__.__name__}. "
                f"Supported versions: {[v.value.id for v in self.supported_versions]}"
            )
        self.version = version

    @classmethod
    def set_local_data(cls, path: str) -> None:
        """Set the base directory for data storage.

        This must be called before using any DataObject subclass.

        Args:
            path: Path to the directory where data objects will be stored.
        """
        cls._local_data = path

    @property
    def local_data(self) -> str:
        """Return the base directory for data storage.

        Raises:
            RuntimeError: If local_data has not been set.
        """
        if self._local_data is None:
            raise RuntimeError(
                "local_data has not been set. "
                "Call DataObject.set_local_data(path) or set it via config."
            )
        return self._local_data

    @property
    def object_stem(self) -> str:
        """Return the object stem (id-version)."""
        return f"{self.id}-{self.version.value.id}"

    @property
    def local_dir(self) -> pathlib.Path:
        """Return the local directory path."""
        return pathlib.Path(self.local_data) / self.object_stem

    def path_to_format(self, fmt: StrEnum) -> pathlib.Path:
        """Return path for a given format.

        Args:
            fmt: Format enum specifying the output format.

        Returns:
            Path to the file or directory for this format.
        """
        return self.local_dir / f"{self.object_stem}.{fmt.value}"

    def exists(self) -> bool:
        """Check whether the master copy of this data object exists.

        Returns:
            True if the master copy file or directory exists, False otherwise.
        """
        return self.path_to_format(self.make_format).exists()

    def _delete_format(self, fmt: StrEnum) -> None:
        """Delete a specific format of the object."""
        format_path = self.path_to_format(fmt)
        if format_path.exists():
            if format_path.is_dir():
                shutil.rmtree(format_path)
            else:
                format_path.unlink()
            logger.info(
                f"deleted_format | object={self.object_stem} fmt={fmt.value}"
            )

    def _convert_formats(self, formats_to_create: Sequence[StrEnum]) -> None:
        """Run each format's conversion method and log a per-format summary.

        Raises:
            NotImplementedError: If conversion method not found.
        """
        for fmt in formats_to_create:
            if fmt == self.make_format:
                continue
            method_name = f"_convert_to_{fmt.value.replace('.', '_')}"
            if not hasattr(self, method_name):
                raise NotImplementedError(
                    f"Conversion method {method_name} not found for format '{fmt.value}'"
                )
            t0 = time.perf_counter()
            getattr(self, method_name)()
            dt = time.perf_counter() - t0
            fmt_path = self.path_to_format(fmt).resolve()
            kvs: dict[str, Any] = {
                "object": self.object_stem,
                "fmt": fmt.value,
                "dur_s": f"{dt:.3f}",
                "bytes": file_or_dir_size_bytes(fmt_path),
                **self._convert_summary(fmt),
                "path": str(fmt_path),
            }
            logger.info(format_summary("convert", kvs))

    @abstractmethod
    def _make(self) -> None:
        """Create and save the object in default format.

        Must be implemented by subclasses to create the actual data.
        """

    async def _amake(self) -> None:
        """Async hook for ``make()``.

        Default runs sync ``_make`` in a thread so it can be awaited from
        a running event loop (e.g. a Dagster asset). Subclasses that have
        an async-native build (``TableFromDB``) override this directly.
        """
        await asyncio.to_thread(self._make)

    # ---- Subclass hooks for the lifecycle summary lines ----------------

    def _make_summary(self) -> dict[str, Any]:
        """Subclass hook contributing ``k=v`` fields to the make_summary.

        Default empty. Overrides should return a small dict (e.g.
        ``{"rows": 100, "cols": 5}``) — these are merged into the
        summary line emitted at the end of ``make()``.
        """
        return {}

    def _convert_summary(self, fmt: StrEnum) -> dict[str, Any]:
        """Subclass hook for the convert_summary line. Default empty."""
        del fmt
        return {}

    def _delete_summary(self) -> dict[str, Any]:
        """Subclass hook for the delete_summary line. Default empty."""
        return {}

    # ---- Public lifecycle methods --------------------------------------

    def make(self, replace: bool = False) -> None:
        """Create the master copy of the object in the default format.

        Args:
            replace: If True, delete existing master copy and all format
                copies, then create master copy anew. If False, raise
                error if master copy already exists.

        Raises:
            FileExistsError: If master copy exists and replace=False.
        """
        if self.exists() and not replace:
            raise FileExistsError(
                f"Object {self.object_stem} already exists in default format ({self.make_format.value}). "
                f"Use replace=True to overwrite."
            )

        if replace:
            self.delete()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        with object_log_context(
            object_stem=self.object_stem,
            local_dir=self.local_dir,
            phase="make",
        ):
            t0 = time.perf_counter()
            try:
                self._make()
            except Exception:
                logger.exception(f"make_failed | object={self.object_stem}")
                raise
            dt = time.perf_counter() - t0
            master_path = self.path_to_format(self.make_format).resolve()
            kvs: dict[str, Any] = {
                "object": self.object_stem,
                "fmt": self.make_format.value,
                "dur_s": f"{dt:.3f}",
                "bytes": file_or_dir_size_bytes(master_path),
                **self._make_summary(),
                "path": str(master_path),
            }
            logger.info(format_summary("make", kvs))

    def convert(self, fmt: StrEnum | None = None, replace: bool = False) -> None:
        """Create a copy of the object in a supported format using the master copy.

        Args:
            fmt: Format to save (StrEnum). If None, saves in all supported formats
                (excluding the default format).
            replace: If True, delete existing copy and recreate. If False, raise
                error if copy already exists.

        Raises:
            FileNotFoundError: If master copy doesn't exist.
            FileExistsError: If format copy exists and replace=False.
            ValueError: If fmt is not a supported format.
        """
        if not self.exists():
            raise FileNotFoundError(
                f"Master copy not found for {self.object_stem}. "
                f"Call make() first to create the master copy in {self.make_format.value} format."
            )

        format_class = type(self.make_format)

        if fmt is None:
            formats_to_create = [f for f in format_class if f != self.make_format]
        else:
            if not isinstance(fmt, format_class):
                raise TypeError(
                    f"Format '{fmt}' not supported. Supported formats: {list(format_class)}"
                )
            if fmt == self.make_format:
                return
            formats_to_create = [fmt]

        for fmt_enum in formats_to_create:
            format_path = self.path_to_format(fmt_enum)
            if format_path.exists() and not replace:
                raise FileExistsError(
                    f"Format '{fmt_enum.value}' already exists for {self.object_stem}. "
                    f"Use replace=True to overwrite."
                )
            if format_path.exists() and replace:
                self._delete_format(fmt_enum)

        with object_log_context(
            object_stem=self.object_stem,
            local_dir=self.local_dir,
            phase="convert",
        ):
            try:
                self._convert_formats(formats_to_create)
            except Exception:
                logger.exception(f"convert_failed | object={self.object_stem}")
                raise

    def delete(self) -> None:
        """Delete all on-disk data for this object.

        Idempotent: returns silently if nothing exists to delete.
        Logs a ``delete_summary`` line with file count + bytes BEFORE
        the rmtree so the per-object log captures the size that was
        reclaimed (the log file itself goes with the rmtree).
        """
        if not self.local_dir.exists():
            return

        # Compute stats up-front so the summary records what was reclaimed.
        files_n = count_files(self.local_dir)
        size_b = file_or_dir_size_bytes(self.local_dir)
        local_dir = self.local_dir.resolve()

        with object_log_context(
            object_stem=self.object_stem,
            local_dir=self.local_dir,
            phase="delete",
        ):
            kvs: dict[str, Any] = {
                "object": self.object_stem,
                "files": files_n,
                "bytes": size_b,
                **self._delete_summary(),
                "path": str(local_dir),
            }
            logger.info(format_summary("delete", kvs))
        # The handler is detached at this point; rmtree removes the log file too.
        shutil.rmtree(self.local_dir)

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

import pathlib
import shutil
from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import dataclass
from enum import (
    Enum,
    StrEnum,
)
from typing import (
    List,
    Tuple,
)

from p40_flowbase.logging import logger


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


class DataObject(ABC):
    """Base class for all data objects.

    Subclasses must define:
        - id: Unique identifier for the data object type.
        - description: Human-readable description.
        - make_format: Default format enum for the make() method.
        - supported_versions: Tuple of version enums.
        - _make_default(): Method to create the object in default format.

    Example:
        class MyTable(TableDataObject):
            id = "my_table"
            description = "My custom table"
            supported_versions = (MyVersions.V1, MyVersions.V2)

            def _make_default(self):
                df = pd.DataFrame(...)
                df.to_parquet(self.path_to_format(TableFormat.PARQUET))
    """

    id: str
    description: str
    version: Enum
    make_format: StrEnum
    supported_versions: Tuple = ()

    # Must be set by project config
    _data_local_tmp: str | None = None

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
    def set_data_local_tmp(cls, path: str) -> None:
        """Set the base directory for data storage.

        This must be called before using any DataObject subclass.

        Args:
            path: Path to the directory where data objects will be stored.
        """
        cls._data_local_tmp = path

    @property
    def data_local_tmp(self) -> str:
        """Return the base directory for data storage.

        Raises:
            RuntimeError: If data_local_tmp has not been set.
        """
        if self._data_local_tmp is None:
            raise RuntimeError(
                "data_local_tmp has not been set. "
                "Call DataObject.set_data_local_tmp(path) or set it via config."
            )
        return self._data_local_tmp

    @property
    def object_stem(self) -> str:
        """Return the object stem (id-version)."""
        return f"{self.id}-{self.version.value.id}"

    @property
    def local_dir(self) -> pathlib.Path:
        """Return the local directory path."""
        return pathlib.Path(self.data_local_tmp) / self.object_stem

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
        """Delete a specific format of the object.

        Args:
            fmt: Format to delete.
        """
        format_path = self.path_to_format(fmt)
        if format_path.exists():
            if format_path.is_dir():
                shutil.rmtree(format_path)
            else:
                format_path.unlink()
            logger.info(f"Deleted format '{fmt.value}' for {self.object_stem}")

    def _convert_formats(self, formats_to_create: List[StrEnum]) -> None:
        """Convert default format to other requested formats.

        Args:
            formats_to_create: List of format enums to create.

        Raises:
            NotImplementedError: If conversion method not found.
        """
        for fmt in formats_to_create:
            if fmt == self.make_format:
                continue
            conversionmethod_name = f"_convert_to_{fmt.value.replace('.', '_')}"
            if hasattr(self, conversionmethod_name):
                getattr(self, conversionmethod_name)()
            else:
                raise NotImplementedError(
                    f"Conversion method {conversionmethod_name} not found for format '{fmt.value}'"
                )

    @abstractmethod
    def _make_default(self) -> None:
        """Create and save the object in default format.

        Must be implemented by subclasses to create the actual data.
        """
        pass

    def make(self, replace: bool = False) -> None:
        """Create the master copy of the object in the default format.

        Args:
            replace: If True, delete existing master copy and all format copies,
                then create master copy anew. If False, raise error if master
                copy already exists.

        Raises:
            FileExistsError: If master copy exists and replace=False.
        """
        if self.exists() and not replace:
            raise FileExistsError(
                f"Object {self.object_stem} already exists in default format ({self.make_format.value}). "
                f"Use replace=True to overwrite."
            )

        if replace:
            self._delete_existing_formats()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._make_default()
        logger.info(f"{self.object_stem} created successfully")

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
            if not isinstance(fmt, StrEnum):
                raise ValueError(
                    f"Format must be a StrEnum type. "
                    f"Supported formats: {list(format_class)}"
                )
            if not isinstance(fmt, format_class):
                raise ValueError(
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
            elif format_path.exists() and replace:
                self._delete_format(fmt_enum)

        self._convert_formats(formats_to_create)

    def _delete_existing_formats(self) -> None:
        """Delete all existing formats of the object."""
        if self.local_dir.exists():
            shutil.rmtree(self.local_dir)
            logger.info(f"Deleted existing formats for {self.object_stem}")

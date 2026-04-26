"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from abc import abstractmethod
from enum import Enum
from typing import (
    ClassVar,
    Generic,
    TypeVar,
    override,
)

import pandas as pd
import pydantic as pyd

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.database import DB
from p40_flowbase.core.formats import TableFormat
from p40_flowbase.logging import logger


class Table(DataObject):
    """Base class for tabular data objects.

    Table objects store data as pandas DataFrames.
    Supported formats:
        - PARQUET: Apache Parquet format (default)
        - CSV: Comma-separated values
        - TSV: Tab-separated values
        - MD: Markdown table
        - JSON: JSON array of records

    Attributes:
        row_schema: Pydantic model class defining the row schema.
    """

    make_format: ClassVar[TableFormat] = TableFormat.PARQUET  # pyright: ignore[reportIncompatibleVariableOverride]
    row_schema: ClassVar[type[pyd.BaseModel]]

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self._df: pd.DataFrame | None = None

    @property
    def df(self) -> pd.DataFrame:
        """Return the object as pandas DataFrame (lazy loading)."""
        if self._df is None:
            self._df = pd.read_parquet(
                self.path_to_format(TableFormat.PARQUET),
                dtype_backend="pyarrow",
            )
        return self._df

    def _convert_to_csv(self) -> None:
        """Convert parquet to csv."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        csv_path = self.path_to_format(TableFormat.CSV)
        df.to_csv(csv_path, index=False)
        logger.info(f"Converted to CSV: {csv_path}")

    def _convert_to_tsv(self) -> None:
        """Convert parquet to tsv."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        tsv_path = self.path_to_format(TableFormat.TSV)
        df.to_csv(tsv_path, sep="\t", index=False)
        logger.info(f"Converted to TSV: {tsv_path}")

    def _convert_to_md(self) -> None:
        """Convert parquet to markdown."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        md_content = df.to_markdown(index=False)
        md_path = self.path_to_format(TableFormat.MD)
        with open(md_path, "w") as f:
            f.write(md_content or "")
        logger.info(f"Converted to Markdown: {md_path}")

    def _convert_to_json(self) -> None:
        """Convert parquet to json."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        json_path = self.path_to_format(TableFormat.JSON)
        df.to_json(json_path, orient="records", indent=2)
        logger.info(f"Converted to JSON: {json_path}")


TDB = TypeVar("TDB", bound=DB)


class TableFromDB(Table, Generic[TDB]):
    """Table built by extracting a DataFrame from a companion ``DB``.

    Subclasses set ``db_class`` and implement ``async _build_df(self, db)``.
    ``_amake`` opens the DB, builds the frame, writes parquet, then closes
    the DB. No ``exists()`` fallback — the upstream DB is assumed to already
    be materialized (in Dagster, ensure this via ``deps=[...]``).

    Example:
        class MyTable(TableFromDB[MyDB]):
            id = "my_table"
            db_class = MyDB
            row_schema = MyRowSchema
            supported_versions = (MyVersions.V1,)

            async def _build_df(self, db: MyDB) -> pd.DataFrame:
                async with db.session_factory() as session:
                    ...
                return df
    """

    db_class: ClassVar[type[DB]]

    @abstractmethod
    async def _build_df(self, db: TDB) -> pd.DataFrame:
        """Return a DataFrame extracted from ``db``.

        Subclasses must implement this method.
        """

    @override
    async def _amake(self) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        db: TDB = self.db_class(self.version)  # type: ignore[assignment]
        try:
            df = await self._build_df(db)
            df.convert_dtypes(dtype_backend="pyarrow").to_parquet(
                self.path_to_format(TableFormat.PARQUET),
                index=False,
            )
        finally:
            await db.close()

    @override
    def _make(self) -> None:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._amake())
        else:
            raise RuntimeError(
                "Cannot call make() from an async context. "
                "Use `await obj._amake()` instead."
            )

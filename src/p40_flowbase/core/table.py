"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
from abc import abstractmethod
from enum import Enum
from typing import (
    ClassVar,
    Generic,
    TypeVar,
    override,
)

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pydantic as pyd

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.database import DB
from p40_flowbase.core.formats import TableFormat
from p40_flowbase.logging import logger


class Table(DataObject):
    """Base class for tabular data objects.

    Table objects store data as Apache Arrow tables backed by Parquet on disk.
    Supported formats:
        - PARQUET: Apache Parquet format (default)
        - CSV: Comma-separated values
        - TSV: Tab-separated values
        - JSON: JSON array of records

    Attributes:
        row_schema: Pydantic model class defining the row schema.
    """

    make_format: ClassVar[TableFormat] = TableFormat.PARQUET  # pyright: ignore[reportIncompatibleVariableOverride]
    row_schema: ClassVar[type[pyd.BaseModel]]

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self._table: pa.Table | None = None

    @property
    def df(self) -> pa.Table:
        """Return the object as a pyarrow Table (lazy loading)."""
        if self._table is None:
            self._table = pq.read_table(self.path_to_format(TableFormat.PARQUET))
        return self._table

    def _convert_to_csv(self) -> None:
        """Convert parquet to csv."""
        src = self.path_to_format(TableFormat.PARQUET)
        dst = self.path_to_format(TableFormat.CSV)
        duckdb.read_parquet(str(src)).write_csv(str(dst), header=True)
        logger.info(f"Converted to CSV: {dst}")

    def _convert_to_tsv(self) -> None:
        """Convert parquet to tsv."""
        src = self.path_to_format(TableFormat.PARQUET)
        dst = self.path_to_format(TableFormat.TSV)
        duckdb.read_parquet(str(src)).write_csv(str(dst), header=True, sep="\t")
        logger.info(f"Converted to TSV: {dst}")

    def _convert_to_json(self) -> None:
        """Convert parquet to json (array of records, indented)."""
        src = self.path_to_format(TableFormat.PARQUET)
        dst = self.path_to_format(TableFormat.JSON)
        rows = pq.read_table(src).to_pylist()
        dst.write_text(json.dumps(rows, indent=2, default=str))
        logger.info(f"Converted to JSON: {dst}")


TDB = TypeVar("TDB", bound=DB)


class TableFromDB(Table, Generic[TDB]):
    """Table built by extracting a pyarrow Table from a companion ``DB``.

    Subclasses set ``db_class`` and implement ``async _build_df(self, db)``.
    ``_amake`` opens the DB, builds the arrow table, writes parquet, then
    closes the DB. No ``exists()`` fallback — the upstream DB is assumed
    to already be materialized (in Dagster, ensure this via ``deps=[...]``).

    Example:
        class MyTable(TableFromDB[MyDB]):
            id = "my_table"
            db_class = MyDB
            row_schema = MyRowSchema
            supported_versions = (MyVersions.V1,)

            async def _build_df(self, db: MyDB) -> pa.Table:
                async with db.session_factory() as session:
                    rows = (await session.exec(select(MyRow))).all()
                return pa.Table.from_pylist([r.model_dump() for r in rows])
    """

    db_class: ClassVar[type[DB]]

    @abstractmethod
    async def _build_df(self, db: TDB) -> pa.Table:
        """Return a pyarrow Table extracted from ``db``.

        Subclasses must implement this method.
        """

    @override
    async def _amake(self) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        db: TDB = self.db_class(self.version)  # type: ignore[assignment]
        try:
            table = await self._build_df(db)
            pq.write_table(table, self.path_to_format(TableFormat.PARQUET))
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

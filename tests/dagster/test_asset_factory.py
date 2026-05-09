"""Tests for `p40_flowbase.dagster.asset` factory.

Regression coverage for the async-in-Dagster-loop bug:

1. `TableFromDB` — sync `_make()` calls `asyncio.run(self._amake())`, which
   crashes inside Dagster's running loop.
2. `Composite` with sync `_make()` that calls `asyncio.run(...)` internally
   (e.g. `WMContentFiles._save_files`) — same crash, but `Composite` has
   no `_amake` override, so the fix relies on the base-class default
   (``DataObject._amake`` → ``asyncio.to_thread(self._make)``).
"""

import asyncio
from enum import Enum
from typing import override

import dagster as dg
import pyarrow as pa
import pydantic as pyd
from sqlmodel import (
    Field,
    SQLModel,
    select,
)

import p40_flowbase as fb
from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.composite import Composite
from p40_flowbase.core.database import DB
from p40_flowbase.core.formats import CompositeFormat, TableFormat
from p40_flowbase.core.table import Table, TableFromDB


class _V(Enum):
    V1 = DataObjectVersion(id="af_v1", name="v1", description="asset factory test")


class _AFRow(pyd.BaseModel):
    n: int


class _PlainTable(Table):
    id = "af_plain_table"
    description = "Plain sync Table"
    supported_versions = (_V.V1,)
    row_schema = _AFRow

    @override
    def _make(self) -> None:
        table = pa.Table.from_pylist([{"n": 1}, {"n": 2}])
        self.save_arrow(table)


class _AFWidget(SQLModel, table=True):
    __tablename__ = "af_widgets"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}
    widget_id: int = Field(default=None, primary_key=True)
    n: int


class _AFDB(DB):
    id = "af_widget_db"
    description = "Asset factory widget DB"
    supported_versions = (_V.V1,)
    tables = [_AFWidget]


class _AFTable(TableFromDB[_AFDB]):
    id = "af_widgets_table"
    description = "Asset factory widgets table"
    supported_versions = (_V.V1,)
    db_class = _AFDB
    row_schema = _AFRow

    @override
    async def _build_df(self, db: _AFDB) -> pa.Table:
        async with db.session_factory() as session:
            result = await session.exec(select(_AFWidget))
            rows = result.all()
        return pa.Table.from_pylist([{"n": r.n} for r in rows])


class _AFComposite(Composite):
    """Composite whose sync ``_make`` itself calls ``asyncio.run(...)``.

    Mirrors the ``WMContentFiles`` pattern. If run directly from a
    running event loop, the inner ``asyncio.run`` crashes — the asset
    factory must drive ``_make`` through the base-class ``_amake``
    which wraps it in ``asyncio.to_thread``.
    """

    id = "af_composite"
    description = "Composite with nested asyncio.run"
    supported_versions = (_V.V1,)

    @override
    def _make(self) -> None:
        asyncio.run(self._write_files())

    async def _write_files(self) -> None:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)
        (files_dir / "hello.txt").write_text("hi\n")


def _materialize(
    asset_def: dg.AssetsDefinition,
    replace: bool = False,
) -> None:
    """Materialize the given asset for partition `af_v1`.

    `dg.materialize_to_memory` is sync; it drives its own event loop to
    execute the async asset body.
    """
    result = dg.materialize_to_memory(
        [asset_def],
        partition_key="af_v1",
        resources={"replace": fb.ReplaceResource(replace=replace)},
    )
    assert result.success


def test_plain_table_asset_materializes(test_local_data):
    asset_def = fb.asset(
        _PlainTable,
        partitions_def=fb.partitions_from_versions((_V.V1,)),
        version_enum_class=_V,
    )
    _materialize(asset_def)

    table = _PlainTable(_V.V1)
    assert table.path_to_format(TableFormat.PARQUET).exists()
    df = table.df
    assert df["n"].to_pylist() == [1, 2]


def test_table_from_db_asset_materializes(test_local_data):
    """Regression: the else branch previously crashed on TableFromDB."""

    async def _seed() -> None:
        db = _AFDB(_V.V1)
        await db.create_tables(replace=True)
        async with db.session_factory() as session:
            session.add(_AFWidget(widget_id=1, n=10))
            session.add(_AFWidget(widget_id=2, n=20))
            await session.commit()
        await db.close()

    asyncio.run(_seed())

    asset_def = fb.asset(
        _AFTable,
        partitions_def=fb.partitions_from_versions((_V.V1,)),
        version_enum_class=_V,
    )
    _materialize(asset_def)

    table = _AFTable(_V.V1)
    assert table.path_to_format(TableFormat.PARQUET).exists()
    df = table.df
    assert sorted(df["n"].to_pylist()) == [10, 20]  # type: ignore[type-var]


def test_composite_asset_materializes(test_local_data):
    """Regression: Composite has no `_amake` override — base default runs
    sync `_make` (with nested `asyncio.run`) in a thread.
    """
    asset_def = fb.asset(
        _AFComposite,
        partitions_def=fb.partitions_from_versions((_V.V1,)),
        version_enum_class=_V,
    )
    _materialize(asset_def)

    composite = _AFComposite(_V.V1)
    files_dir = composite.path_to_format(CompositeFormat.FILES)
    assert (files_dir / "hello.txt").read_text() == "hi\n"

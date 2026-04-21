"""Tests for TableFromDB."""

from enum import Enum

import pandas as pd
import pydantic as pyd
import pytest
from sqlmodel import (
    Field,
    SQLModel,
)

from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.database import DB
from p40_flowbase.core.formats import TableFormat
from p40_flowbase.core.table import TableFromDB


class _Version(Enum):
    V1 = DataObjectVersion(id="test_tfd", name="TFD", description="Test TFD")


class _Widget(SQLModel, table=True):
    __tablename__ = "test_tfd_widgets"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}
    widget_id: int = Field(default=None, primary_key=True)
    name: str
    value: int


class _WidgetDB(DB):
    id = "test_tfd_widget_db"
    description = "Test widget DB"
    supported_versions = (_Version.V1,)
    tables = [_Widget]


class _WidgetRow(pyd.BaseModel):
    widget_id: int
    name: str
    value: int


class _WidgetsTable(TableFromDB[_WidgetDB]):
    id = "test_tfd_widgets_table"
    description = "Test widgets table"
    supported_versions = (_Version.V1,)
    db_class = _WidgetDB
    row_schema = _WidgetRow

    async def _build_df(self, db: _WidgetDB) -> pd.DataFrame:
        from sqlmodel import select

        async with db.session_factory() as session:
            result = await session.exec(select(_Widget))
            rows = result.all()

        return pd.DataFrame(
            [{"widget_id": r.widget_id, "name": r.name, "value": r.value} for r in rows]
        )


@pytest.fixture
async def populated_widget_db(test_local_data):
    db = _WidgetDB(_Version.V1)
    await db.create_tables(replace=True)
    async with db.session_factory() as session:
        session.add(_Widget(widget_id=1, name="alpha", value=10))
        session.add(_Widget(widget_id=2, name="beta", value=20))
        await session.commit()
    yield db
    await db.close()


class TestTableFromDB:
    @pytest.mark.asyncio
    async def test_amake_writes_parquet_from_db(self, populated_widget_db):
        table = _WidgetsTable(_Version.V1)
        await table._amake()
        parquet_path = table.path_to_format(TableFormat.PARQUET)
        assert parquet_path.exists()
        result_df = pd.read_parquet(parquet_path)
        assert list(result_df.columns) == ["widget_id", "name", "value"]
        assert len(result_df) == 2
        assert set(result_df["name"]) == {"alpha", "beta"}

    @pytest.mark.asyncio
    async def test_df_property_reads_written_parquet(self, populated_widget_db):
        table = _WidgetsTable(_Version.V1)
        await table._amake()
        df = table.df
        assert len(df) == 2
        assert set(df["value"]) == {10, 20}

    def test_sync_make_raises_in_async_context_via_asyncio_run_fail(self):
        """``_make()`` delegates to ``_amake()`` via ``asyncio.run``.

        Calling it from a synchronous context should work normally; calling it
        when an event loop is already running should raise RuntimeError.
        """
        import asyncio

        async def run_from_async():
            table = _WidgetsTable(_Version.V1)
            with pytest.raises(RuntimeError, match="async context"):
                table._make()

        asyncio.run(run_from_async())

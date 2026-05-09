"""Tests for `p40_flowbase.helpers.jinja_templates` and the default
`Table._make` SQL-template path.

Fixture templates live in
``tests/_fixtures/sample_pkg/resources/templates/tables/``. The
``sample_pkg`` package is added to ``pythonpath`` via
``pyproject.toml``'s ``[tool.pytest.ini_options]``.
"""

import datetime as _dt
import decimal as _dc
from enum import Enum
from typing import (
    Optional,  # pyright: ignore[reportDeprecated]
    override,
)

import pyarrow as pa
import pyarrow.parquet as pq
import pydantic as pyd
import pytest

from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.formats import TableFormat
from p40_flowbase.core.table import Table
from p40_flowbase.helpers.arrow_schema import (
    arrow_schema_from_pydantic,
    validate_arrow_against_pydantic,
)
from p40_flowbase.helpers.jinja_templates import render_jinja_template


class _V(Enum):
    V1 = DataObjectVersion(id="st_v1", name="v1", description="sql_templates test")


class _SampleWidgetRow(pyd.BaseModel):
    widget_id: int
    name: str
    value: int


class _SampleWidgetsTable(Table):
    """Uses make_via_sql_template explicitly with a Jinja var."""

    id = "sample_widgets"
    description = "Widgets sourced from sample_widgets.sql.jinja"
    supported_versions = (_V.V1,)
    row_schema = _SampleWidgetRow
    template_package = "sample_pkg"

    @override
    def _make(self) -> None:
        self.make_via_sql_template(template_vars={"third_value": 30})


class _DefaultMakeRow(pyd.BaseModel):
    widget_id: int
    name: str


class _DefaultMakeWidgetsTable(Table):
    """No `_make` override — exercises the default Table._make path.

    `template_package = "sample_pkg"` is required because the class is
    defined under `tests.helpers...` (auto-inference would pick
    `tests`, which has no resources tree). Real users keep their
    Tables in their own package and don't need this override.
    """

    id = "default_make_widgets"
    description = "Default _make path test"
    supported_versions = (_V.V1,)
    row_schema = _DefaultMakeRow
    template_package = "sample_pkg"


class _BadSchemaWidgetsTable(Table):
    """Template returns wrong columns; should raise before write."""

    id = "bad_schema_widgets"
    description = "Schema-mismatch test"
    supported_versions = (_V.V1,)
    row_schema = _SampleWidgetRow
    template_package = "sample_pkg"


# ---------- render_jinja_template -----------------------------------------


def test_render_jinja_template_loads_from_fixture_package():
    sql = render_jinja_template(
        "sample_widgets.sql.jinja",
        package="sample_pkg",
        third_value=99,
    )
    assert "VALUES" in sql
    assert "(3, 'gamma', 99)" in sql


def test_render_jinja_template_missing_template_raises():
    with pytest.raises(FileNotFoundError):
        render_jinja_template("does_not_exist.sql.jinja", package="sample_pkg")


# ---------- arrow_schema_from_pydantic ----------------------------------


def test_arrow_schema_from_pydantic_primitives():
    class _M(pyd.BaseModel):
        i: int
        f: float
        b: bool
        s: str
        by: bytes
        ts: _dt.datetime
        d: _dt.date
        dec: _dc.Decimal

    schema = arrow_schema_from_pydantic(_M)
    assert schema.field("i").type == pa.int64()
    assert schema.field("f").type == pa.float64()
    assert schema.field("b").type == pa.bool_()
    assert schema.field("s").type == pa.string()
    assert schema.field("by").type == pa.binary()
    assert schema.field("ts").type == pa.timestamp("us")
    assert schema.field("d").type == pa.date32()
    assert schema.field("dec").type == pa.decimal128(38, 18)
    for f in schema:
        assert not f.nullable


def test_arrow_schema_from_pydantic_optional_pipe():
    class _M(pyd.BaseModel):
        n: int | None = None

    schema = arrow_schema_from_pydantic(_M)
    assert schema.field("n").type == pa.int64()
    assert schema.field("n").nullable


def test_arrow_schema_from_pydantic_optional_typing():
    class _M(pyd.BaseModel):
        n: Optional[int] = None  # noqa: UP045  # pyright: ignore[reportDeprecated]

    schema = arrow_schema_from_pydantic(_M)
    assert schema.field("n").type == pa.int64()
    assert schema.field("n").nullable


def test_arrow_schema_from_pydantic_unsupported_union_raises():
    class _M(pyd.BaseModel):
        x: int | str

    with pytest.raises(TypeError, match="Cannot map Union"):
        arrow_schema_from_pydantic(_M)


def test_arrow_schema_from_pydantic_unsupported_type_raises():
    class _M(pyd.BaseModel):
        x: list[int]

    with pytest.raises(TypeError, match="No Arrow mapping"):
        arrow_schema_from_pydantic(_M)


# ---------- validate_arrow_against_pydantic -----------------------------


def test_validate_passes_on_exact_match():
    table = pa.Table.from_pylist([
        {"widget_id": 1, "name": "a", "value": 10},
        {"widget_id": 2, "name": "b", "value": 20},
    ])
    validate_arrow_against_pydantic(arrow_table=table, model=_SampleWidgetRow)


def test_validate_passes_on_int_class_compatibility():
    """int32 in Arrow should validate against Python `int` (int64 expected)."""
    schema = pa.schema([
        pa.field("widget_id", pa.int32()),
        pa.field("name", pa.string()),
        pa.field("value", pa.int32()),
    ])
    table = pa.Table.from_pydict(
        {"widget_id": [1], "name": ["a"], "value": [10]},
        schema=schema,
    )
    validate_arrow_against_pydantic(arrow_table=table, model=_SampleWidgetRow)


def test_validate_reports_all_diffs():
    table = pa.Table.from_pylist([{"widget_id": 1, "extra_col": "x"}])
    with pytest.raises(ValueError, match="does not match Pydantic schema") as exc_info:
        validate_arrow_against_pydantic(
            arrow_table=table, model=_SampleWidgetRow,
        )
    msg = str(exc_info.value)
    assert "missing column 'name'" in msg
    assert "missing column 'value'" in msg
    assert "extra_col" in msg


def test_validate_reports_type_mismatch():
    table = pa.Table.from_pydict({
        "widget_id": pa.array([1], type=pa.int64()),
        "name": pa.array(["a"], type=pa.string()),
        "value": pa.array([1.5], type=pa.float64()),  # expected int
    })
    with pytest.raises(ValueError, match="column 'value'"):
        validate_arrow_against_pydantic(
            arrow_table=table, model=_SampleWidgetRow,
        )


# ---------- Table.make_via_sql_template (explicit) ----------------------


def test_make_via_sql_template_writes_parquet(test_local_data):
    table = _SampleWidgetsTable(_V.V1)
    table.make()

    pq_path = table.path_to_format(TableFormat.PARQUET)
    assert pq_path.exists()
    arrow = pq.read_table(pq_path)
    assert arrow.column_names == ["widget_id", "name", "value"]
    assert arrow["value"].to_pylist() == [10, 20, 30]


def test_make_via_sql_template_schema_mismatch_raises_before_write(
    test_local_data,
):
    bad = _BadSchemaWidgetsTable(_V.V1)
    with pytest.raises(ValueError, match="does not match Pydantic schema"):
        bad.make()
    assert not bad.path_to_format(TableFormat.PARQUET).exists()


# ---------- Default Table._make (no override) — headline test -----------


def test_default_make_path_writes_parquet(test_local_data):
    """Headline: zero-`_make` Table materializes via the convention."""
    table = _DefaultMakeWidgetsTable(_V.V1)
    table.make()

    pq_path = table.path_to_format(TableFormat.PARQUET)
    assert pq_path.exists()
    arrow = pq.read_table(pq_path)
    assert arrow.column_names == ["widget_id", "name"]
    assert arrow["widget_id"].to_pylist() == [10, 20]


# ---------- Direct save_arrow validation runs at the write boundary -----


def test_save_arrow_validates_and_writes(test_local_data):
    table = _SampleWidgetsTable(_V.V1)
    table.local_dir.mkdir(parents=True, exist_ok=True)
    arrow = pa.Table.from_pylist([
        {"widget_id": 1, "name": "a", "value": 10},
    ])
    table.save_arrow(arrow)
    assert table.path_to_format(TableFormat.PARQUET).exists()


def test_save_arrow_raises_before_write_on_mismatch(test_local_data):
    table = _SampleWidgetsTable(_V.V1)
    table.delete()  # session-scoped tmp dir → clear any prior write
    table.local_dir.mkdir(parents=True, exist_ok=True)
    bad = pa.Table.from_pylist([{"widget_id": 1}])
    with pytest.raises(ValueError, match="does not match Pydantic schema"):
        table.save_arrow(bad)
    assert not table.path_to_format(TableFormat.PARQUET).exists()


def test_save_arrow_validate_false_skips_check(test_local_data):
    table = _SampleWidgetsTable(_V.V1)
    table.local_dir.mkdir(parents=True, exist_ok=True)
    bad = pa.Table.from_pylist([{"widget_id": 1}])
    table.save_arrow(bad, validate=False)
    assert table.path_to_format(TableFormat.PARQUET).exists()



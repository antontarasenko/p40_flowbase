"""Tests for ``ck.FieldsInQuote``: a row's structured fields proven against
the row's own quote after folding, the table read alone."""

from __future__ import annotations

from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    override,
)

import pyarrow as pa
import pytest

import p40_flowbase as fb
from p40_flowbase import checks as ck
from p40_flowbase import schemas as sc
from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.helpers import arrow_schema_from_pydantic

if TYPE_CHECKING:
    import pydantic as pyd


class _V(Enum):
    V1 = DataObjectVersion(id="fiq_v1", name="v1", description="fields tests")


class _Card(sc.MetricObservation):
    price_text: str | None = None
    size_text: str | None = None


CARD = "Rana Tagliatelle Fresh Pasta 9 oz $3.99 Add to cart"
NBSP = "\u00a0"


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "ref_id": "rana_tagliatelle",
        "metric": "price_usd",
        "source_url": "https://g.com/pasta",
        "quote": CARD,
        "price_text": "$3.99",
        "size_text": "9 oz",
        **overrides,
    }
    return {k: v for k, v in row.items() if v is not None}


class _FT(fb.Table):
    id: ClassVar[str] = "fiq_table"
    description: ClassVar[str] = "FieldsInQuote test table"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _Card
    rows: ClassVar[list[dict[str, Any]]] = []

    @override
    def _make(self) -> None:
        validated = [_Card.model_validate(r).model_dump() for r in type(self).rows]
        self.save_arrow(
            pa.Table.from_pylist(validated, schema=arrow_schema_from_pydantic(_Card))
        )


def _made(rows: list[dict[str, Any]], test_local_data: str) -> _FT:
    del test_local_data
    _FT.rows = rows
    obj = _FT(_V.V1)
    obj.make(replace=True)
    return obj


class TestFieldsInQuote:
    def test_green_fields_in_the_card(self, test_local_data):
        obj = _made([_row()], test_local_data)
        check = ck.FieldsInQuote(fields=("price_text", "size_text"))
        check.run(obj)
        report = check.report(obj)
        assert [s.status for s in report] == ["verified", "verified"]
        assert [s.field for s in report] == ["price_text", "size_text"]

    def test_red_price_from_the_next_card(self, test_local_data):
        obj = _made([_row(price_text="$4.49")], test_local_data)
        check = ck.FieldsInQuote(fields=("price_text", "size_text"))
        with pytest.raises(ck.CheckFailedError, match="field_missing for 'rana"):
            check.run(obj)
        missing = [s for s in check.report(obj) if s.status == "field_missing"]
        assert [s.field for s in missing] == ["price_text"]
        assert missing[0].message is not None
        assert "$4.49" in missing[0].message

    def test_folding_bridges_renderings(self, test_local_data):
        obj = _made([_row(size_text=f"9{NBSP}OZ")], test_local_data)
        ck.FieldsInQuote(fields=("size_text",)).run(obj)

    def test_null_and_empty_fields_are_passed_over(self, test_local_data):
        obj = _made(
            [_row(size_text=None), _row(ref_id="r2", size_text="")], test_local_data
        )
        report = ck.FieldsInQuote(fields=("price_text", "size_text")).report(obj)
        assert [(s.ref_id, s.field) for s in report] == [
            ("rana_tagliatelle", "price_text"),
            ("r2", "price_text"),
        ]

    def test_absent_column_fails(self, test_local_data):
        obj = _made([_row()], test_local_data)
        with pytest.raises(ck.CheckFailedError, match="no column weight_text"):
            ck.FieldsInQuote(fields=("weight_text",)).run(obj)

    def test_requires_a_field(self):
        with pytest.raises(ValueError, match="at least one field"):
            ck.FieldsInQuote(fields=())

"""Tests for ``ck.QuotesVerified``: structural quote re-verification.

Builds a real ``Table`` whose ``row_schema`` is ``sc.Observation``,
materializes rows, and runs the check against a dict-backed resolver.
"""

from __future__ import annotations

from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import pyarrow as pa
import pydantic as pyd
import pytest

import p40_flowbase as fb
from p40_flowbase import checks as ck
from p40_flowbase import schemas as sc
from p40_flowbase.core.base import (
    DataObject,
    DataObjectVersion,
)
from p40_flowbase.helpers import arrow_schema_from_pydantic


class _V(Enum):
    V1 = DataObjectVersion(id="sch_v1", name="v1", description="schemas tests")


BODY = "<p>Revenue was <b>$57.0 billion</b>, up 62% from a year ago.</p>"
TRANSCRIPT = "Total\n2,070 relocated restaurants in fiscal 2025."

SOURCES: dict[tuple[str, str | None], str] = {
    ("https://e.com/10q", None): BODY,
    ("https://e.com/report.pdf", "filings.files/report.pdftotext.txt"): TRANSCRIPT,
}


def _resolver(obj: DataObject, url: str, transcript: str | None) -> str | None:
    del obj
    return SOURCES.get((url, transcript))


def _row(**overrides) -> dict[str, Any]:
    row = {
        "ref_id": "nvda_revenue_q3_fy2026",
        "metric": "revenue_gaap_b_usd",
        "source_url": "https://e.com/10q",
        "quote": "Revenue was <b>$57.0 billion</b>",
        "value_float": 57.0,
        **overrides,
    }
    return {k: v for k, v in row.items() if v is not None}


class _QT(fb.Table):
    id: ClassVar[str] = "sch_quotes_table"
    description: ClassVar[str] = "QuotesVerified test table"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    row_schema: ClassVar[type[pyd.BaseModel]] = sc.Observation
    rows: ClassVar[list[dict[str, Any]]] = []

    @override
    def _make(self) -> None:
        validated = [
            sc.Observation.model_validate(r).model_dump() for r in type(self).rows
        ]
        self.save_arrow(
            pa.Table.from_pylist(
                validated, schema=arrow_schema_from_pydantic(sc.Observation)
            )
        )


def _made(rows: list[dict[str, Any]], test_local_data: str) -> _QT:
    del test_local_data
    _QT.rows = rows
    obj = _QT(_V.V1)
    obj.make(replace=True)
    return obj


class TestQuotesVerified:
    def test_green_raw_body_and_transcript(self, test_local_data):
        obj = _made(
            [
                _row(),
                _row(
                    ref_id="restaurant_relocations",
                    metric="relocated_restaurants_cnt",
                    source_url="https://e.com/report.pdf",
                    source_transcript="filings.files/report.pdftotext.txt",
                    quote="Total\n2,070",
                    value_float=None,
                    value_int=2070,
                ),
            ],
            test_local_data,
        )
        ck.QuotesVerified(resolver=_resolver).run(obj)

    def test_red_fabricated_quote(self, test_local_data):
        obj = _made([_row(quote="Revenue was $58.0 billion")], test_local_data)
        with pytest.raises(ck.CheckFailedError, match="byte-identical"):
            ck.QuotesVerified(resolver=_resolver).run(obj)

    def test_red_different_rendering_gets_hint(self, test_local_data):
        obj = _made([_row(quote="Revenue was  <b>$57.0 billion</b>")], test_local_data)
        with pytest.raises(ck.CheckFailedError, match="different rendering"):
            ck.QuotesVerified(resolver=_resolver).run(obj)

    def test_offset_green_and_red(self, test_local_data):
        offset = BODY.index("Revenue was")
        obj = _made([_row(quote_offset_char=offset)], test_local_data)
        ck.QuotesVerified(resolver=_resolver).run(obj)

        obj = _made([_row(quote_offset_char=offset + 1)], test_local_data)
        with pytest.raises(ck.CheckFailedError, match="quote_offset_char"):
            ck.QuotesVerified(resolver=_resolver).run(obj)

    def test_on_missing_policies(self, test_local_data):
        rows = [_row(), _row(ref_id="unstored", source_url="https://e.com/gone")]
        obj = _made(rows, test_local_data)

        with pytest.raises(ck.CheckFailedError, match="no stored source"):
            ck.QuotesVerified(resolver=_resolver).run(obj)
        ck.QuotesVerified(resolver=_resolver, on_missing="skip").run(obj)
        ck.QuotesVerified(resolver=_resolver, on_missing=0.5).run(obj)
        with pytest.raises(ck.CheckFailedError, match="required 90"):
            ck.QuotesVerified(resolver=_resolver, on_missing=0.9).run(obj)

    def test_on_missing_param_validation(self):
        with pytest.raises(ValueError, match="fail"):
            ck.QuotesVerified(resolver=_resolver, on_missing="maybe")
        with pytest.raises(ValueError, match="fraction"):
            ck.QuotesVerified(resolver=_resolver, on_missing=0.0)

    def test_attached_to_lifecycle(self, test_local_data):
        class _QTChecked(_QT):
            id: ClassVar[str] = "sch_quotes_table_checked"
            checks: ClassVar[tuple[fb.Check, ...]] = (
                ck.QuotesVerified(resolver=_resolver),
            )

        _QTChecked.rows = [_row(quote="fabricated quote")]
        with pytest.raises(ck.CheckFailedError):
            _QTChecked(_V.V1).make(replace=True)

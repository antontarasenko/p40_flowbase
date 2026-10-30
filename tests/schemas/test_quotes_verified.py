"""Tests for ``ck.QuotesVerified``: structural quote re-verification.

Builds a real ``Table`` whose ``row_schema`` is ``sc.Observation``,
materializes rows, and runs the check against a dict-backed resolver, the
0.8.2 path, and against a content-addressed ``ArtifactStore``.
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
from p40_flowbase.helpers import (
    arrow_schema_from_pydantic,
    quotes,
)


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


def _store_for(root: Any) -> Any:
    return lambda obj: quotes.ArtifactStore(root)


class TestQuotesVerifiedStore:
    def test_exactly_one_of_store_and_resolver(self):
        with pytest.raises(ValueError, match="exactly one"):
            ck.QuotesVerified()
        with pytest.raises(ValueError, match="exactly one"):
            ck.QuotesVerified(store=_store_for("x"), resolver=_resolver)

    def test_green_by_digest_and_offset(self, test_local_data, tmp_path):
        store = quotes.ArtifactStore(tmp_path)
        sha = store.put(BODY)
        resliced = quotes.reslice_quote(
            quote="revenue  was <B>$57.0 billion", artifact=BODY
        )
        assert resliced is not None
        obj = _made(
            [
                _row(
                    artifact_sha256=sha,
                    quote=resliced.quote,
                    quote_offset_char=resliced.start,
                )
            ],
            test_local_data,
        )
        check = ck.QuotesVerified(store=_store_for(tmp_path))
        check.run(obj)
        [status] = check.report(obj)
        assert status.status == "verified"
        assert status.occurrences == 1
        assert status.hint is None

    def test_statuses_in_the_report(self, test_local_data, tmp_path):
        store = quotes.ArtifactStore(tmp_path)
        sha = store.put(BODY)
        offset = BODY.index("Revenue was")
        obj = _made(
            [
                _row(ref_id="ok", artifact_sha256=sha, quote_offset_char=offset),
                _row(ref_id="unanchored", artifact_sha256=sha),
                _row(ref_id="moved", artifact_sha256=sha, quote_offset_char=offset + 1),
                _row(ref_id="fabricated", artifact_sha256=sha, quote="Revenue was $58"),
                _row(
                    ref_id="rendering",
                    artifact_sha256=sha,
                    quote="Revenue was  <b>$57.0 billion</b>",
                ),
                _row(ref_id="gone", artifact_sha256="0" * 64),
                _row(ref_id="legacy_row"),
            ],
            test_local_data,
        )
        report = ck.QuotesVerified(store=_store_for(tmp_path)).report(obj)
        by_id = {s.ref_id: s for s in report}
        assert by_id["ok"].status == "verified"
        assert by_id["unanchored"].status == "verified"
        assert by_id["moved"].status == "offset_mismatch"
        assert by_id["fabricated"].status == "quote_not_found"
        assert by_id["fabricated"].hint is None
        assert by_id["rendering"].status == "quote_not_found"
        assert by_id["rendering"].hint == "normalized"
        assert "reslice" in (by_id["rendering"].message or "")
        assert by_id["gone"].status == "artifact_missing"
        assert by_id["legacy_row"].status == "artifact_missing"
        assert all(s.source_url for s in report)
        rows = [sc.QuoteStatus.model_validate(s.model_dump()) for s in report]
        assert len(rows) == 7

    def test_run_names_the_status(self, test_local_data, tmp_path):
        store = quotes.ArtifactStore(tmp_path)
        sha = store.put(BODY)
        obj = _made(
            [_row(artifact_sha256=sha, quote_offset_char=BODY.index("was"))],
            test_local_data,
        )
        with pytest.raises(ck.CheckFailedError, match="offset_mismatch"):
            ck.QuotesVerified(store=_store_for(tmp_path)).run(obj)

    def test_refetched_artifact_is_a_hash_mismatch(self, test_local_data, tmp_path):
        store = quotes.ArtifactStore(tmp_path)
        sha = store.put(BODY)
        obj = _made([_row(artifact_sha256=sha)], test_local_data)
        check = ck.QuotesVerified(store=_store_for(tmp_path))
        check.run(obj)
        store.path_of(sha).write_bytes(BODY.replace("62%", "63%").encode("utf-8"))
        [status] = check.report(obj)
        assert status.status == "hash_mismatch"
        with pytest.raises(ck.CheckFailedError, match="hash_mismatch"):
            check.run(obj)
        with pytest.raises(ck.CheckFailedError, match="hash_mismatch"):
            ck.QuotesVerified(store=_store_for(tmp_path), on_missing="skip").run(obj)
        store.path_of(sha).unlink()
        [status] = check.report(obj)
        assert status.status == "artifact_missing"

    def test_any_source_answering_a_digest(self, test_local_data):
        class _Manifest:
            def __init__(self, texts: dict[str, str]) -> None:
                self.texts = texts

            def get(self, sha256: str) -> str | None:
                return self.texts.get(sha256)

        sha = quotes.sha256_of_text(BODY)
        obj = _made(
            [_row(artifact_sha256=sha), _row(ref_id="stale", artifact_sha256="1" * 64)],
            test_local_data,
        )
        manifest = _Manifest({sha: BODY, "1" * 64: BODY})
        report = ck.QuotesVerified(store=lambda obj: manifest).report(obj)
        assert [s.status for s in report] == ["verified", "hash_mismatch"]

    def test_resolver_path_checks_a_digest_when_the_row_has_one(self, test_local_data):
        obj = _made(
            [
                _row(artifact_sha256=quotes.sha256_of_text(BODY)),
                _row(ref_id="stale", artifact_sha256="0" * 64),
            ],
            test_local_data,
        )
        report = ck.QuotesVerified(resolver=_resolver).report(obj)
        assert [s.status for s in report] == ["verified", "hash_mismatch"]

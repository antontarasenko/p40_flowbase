"""Tests for the ``p40_flowbase.checks`` post-make assertion system.

Each built-in gets one green-path test and one red-path test, plus a
small set of integration tests that prove the lifecycle (sync ``make``,
async ``amake``, request-DB ``make``) actually invokes ``checks`` and
propagates :class:`p40_flowbase.checks.CheckFailedError` to the caller.
"""

from __future__ import annotations

import asyncio
import uuid
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
from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.formats import CompositeFormat
from p40_flowbase.http.models import HTTPRequest


class _V(Enum):
    V1 = DataObjectVersion(id="ck_v1", name="v1", description="checks tests")


# ----- Table fixture -------------------------------------------------------


class _TRow(pyd.BaseModel):
    city: str
    n: int


class _T(fb.Table):
    id: ClassVar[str] = "ck_table"
    description: ClassVar[str] = "checks test table"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _TRow

    @override
    def _make(self) -> None:
        self.save_arrow(pa.Table.from_pylist([
            {"city": "A", "n": 1},
            {"city": "B", "n": 2},
        ]))


class _TWithNulls(fb.Table):
    id: ClassVar[str] = "ck_table_with_nulls"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _TRow

    @override
    def _make(self) -> None:
        # PyArrow accepts None per column even when Pydantic field is non-optional;
        # the schema check passes because pa.string() accepts nulls.
        self.save_arrow(pa.Table.from_pylist([
            {"city": "A", "n": 1},
            {"city": None, "n": 2},
        ]))


class _TDup(fb.Table):
    id: ClassVar[str] = "ck_table_dup"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _TRow

    @override
    def _make(self) -> None:
        self.save_arrow(pa.Table.from_pylist([
            {"city": "A", "n": 1},
            {"city": "A", "n": 2},
        ]))


# ----- Composite fixtures --------------------------------------------------


class _C(fb.Composite):
    """Composite with two non-empty JSON files."""

    id: ClassVar[str] = "ck_composite"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)
        (files_dir / "a.json").write_text('{"x": 1}')
        (files_dir / "b.json").write_text('{"x": 2}')


class _CEmpty(fb.Composite):
    """Composite whose only file is 0 bytes."""

    id: ClassVar[str] = "ck_composite_empty"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)
        (files_dir / "empty.txt").write_text("")


class _CNoFiles(fb.Composite):
    """Composite that creates only the FILES dir, no contents."""

    id: ClassVar[str] = "ck_composite_no_files"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)


# ----- HTTPDB fixture ------------------------------------------------------


class _HTTPDB(fb.HTTPDB):
    id: ClassVar[str] = "ck_http_db"
    description: ClassVar[str] = "checks test HTTP DB"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    tables: ClassVar[list[Any]] = [fb.HTTPRequest]

    async def _populate_http_requests(self) -> uuid.UUID:  # pragma: no cover  # stub for the lifecycle test
        return uuid.uuid4()


async def _seed_http(db: _HTTPDB, statuses: list[int | None]) -> None:
    """Insert one HTTPRequest row per ``statuses`` entry."""
    async with db.session_factory() as session:
        for status in statuses:
            session.add(HTTPRequest(
                request_url="http://example.invalid",
                request_method="GET",
                response_status=status,
            ))
        await session.commit()


# ----- Pydantic schema for SchemaMatches ----------------------------------


class _RespSchema(pyd.BaseModel):
    x: int


# =====================================================================
# Table checks
# =====================================================================


def test_min_rows_pass(test_local_data) -> None:
    obj = _T(_V.V1)
    obj.make(replace=True)
    ck.MinRows(2).run(obj)


def test_min_rows_fail(test_local_data) -> None:
    obj = _T(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="min_rows"):
        ck.MinRows(100).run(obj)


def test_no_nulls_pass(test_local_data) -> None:
    obj = _T(_V.V1)
    obj.make(replace=True)
    ck.NoNulls("city", "n").run(obj)


def test_no_nulls_fail(test_local_data) -> None:
    obj = _TWithNulls(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="no_nulls"):
        ck.NoNulls("city").run(obj)


def test_unique_pass(test_local_data) -> None:
    obj = _T(_V.V1)
    obj.make(replace=True)
    ck.Unique("city").run(obj)


def test_unique_fail(test_local_data) -> None:
    obj = _TDup(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="unique"):
        ck.Unique("city").run(obj)


# =====================================================================
# Composite checks
# =====================================================================


def test_min_files_pass(test_local_data) -> None:
    obj = _C(_V.V1)
    obj.make(replace=True)
    ck.MinFiles(1).run(obj)


def test_min_files_fail(test_local_data) -> None:
    obj = _CNoFiles(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="min_files"):
        ck.MinFiles(1).run(obj)


def test_no_empty_files_pass(test_local_data) -> None:
    obj = _C(_V.V1)
    obj.make(replace=True)
    ck.NoEmptyFiles().run(obj)


def test_no_empty_files_fail(test_local_data) -> None:
    obj = _CEmpty(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="no_empty_files"):
        ck.NoEmptyFiles().run(obj)


def test_min_file_size_pass(test_local_data) -> None:
    obj = _C(_V.V1)
    obj.make(replace=True)
    ck.MinFileSize(bytes_=1).run(obj)


def test_min_file_size_fail(test_local_data) -> None:
    obj = _C(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="min_file_size"):
        ck.MinFileSize(bytes_=10_000).run(obj)


def test_schema_matches_pass(test_local_data) -> None:
    obj = _C(_V.V1)
    obj.make(replace=True)
    ck.SchemaMatches(_RespSchema).run(obj)


def test_schema_matches_fail(test_local_data) -> None:
    """Composite with a JSON file that doesn't match the schema."""

    class _CBadJson(fb.Composite):
        id: ClassVar[str] = "ck_composite_bad_json"
        description: ClassVar[str] = "."
        supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)

        @override
        def _make(self) -> None:
            files_dir = self.path_to_format(CompositeFormat.FILES)
            files_dir.mkdir(parents=True, exist_ok=True)
            (files_dir / "bad.json").write_text('{"y": "wrong-shape"}')

    obj = _CBadJson(_V.V1)
    obj.make(replace=True)
    with pytest.raises(ck.CheckFailedError, match="schema_matches"):
        ck.SchemaMatches(_RespSchema).run(obj)


# =====================================================================
# Request-DB checks
# =====================================================================


def test_min_requests_pass(test_local_data) -> None:
    async def _go() -> None:
        db = _HTTPDB(_V.V1)
        await db.create_tables(replace=True)
        await _seed_http(db, [200, 200, 200])
        await ck.MinRequests(1).arun(db)
        await db.close()

    asyncio.run(_go())


def test_min_requests_fail(test_local_data) -> None:
    async def _go() -> None:
        db = _HTTPDB(_V.V1)
        await db.create_tables(replace=True)
        with pytest.raises(ck.CheckFailedError, match="min_requests"):
            await ck.MinRequests(1).arun(db)
        await db.close()

    asyncio.run(_go())


def test_max_failure_rate_pass(test_local_data) -> None:
    async def _go() -> None:
        db = _HTTPDB(_V.V1)
        await db.create_tables(replace=True)
        # 1/3 = 0.33 failed (one 500 among three rows), tolerance 0.5
        await _seed_http(db, [200, 200, 500])
        await ck.MaxFailureRate(frac=0.5).arun(db)
        await db.close()

    asyncio.run(_go())


def test_max_failure_rate_fail(test_local_data) -> None:
    async def _go() -> None:
        db = _HTTPDB(_V.V1)
        await db.create_tables(replace=True)
        # 100% failed; default frac=0.0 forbids any.
        await _seed_http(db, [500, 500, 500])
        with pytest.raises(ck.CheckFailedError, match="max_failure_rate"):
            await ck.MaxFailureRate(frac=0.0).arun(db)
        await db.close()

    asyncio.run(_go())


def test_max_failure_rate_zero_total_passes(test_local_data) -> None:
    """Empty DB short-circuits to pass; emptiness is MinRequests's job."""

    async def _go() -> None:
        db = _HTTPDB(_V.V1)
        await db.create_tables(replace=True)
        await ck.MaxFailureRate(frac=0.0).arun(db)
        await db.close()

    asyncio.run(_go())


# =====================================================================
# Lifecycle integration
# =====================================================================


class _TFailingCheck(fb.Table):
    """Table whose attached check always fails — exercises sync make()."""

    id: ClassVar[str] = "ck_table_failing_check"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _TRow
    checks: ClassVar[tuple[fb.Check, ...]] = (ck.MinRows(100),)

    @override
    def _make(self) -> None:
        self.save_arrow(pa.Table.from_pylist([{"city": "A", "n": 1}]))


def test_sync_make_runs_checks_and_fails(test_local_data) -> None:
    obj = _TFailingCheck(_V.V1)
    with pytest.raises(ck.CheckFailedError, match="min_rows"):
        obj.make(replace=True)


def test_async_amake_runs_checks_and_fails(test_local_data) -> None:
    """``amake`` must run the same checks as ``make``."""
    obj = _TFailingCheck(_V.V1)
    with pytest.raises(ck.CheckFailedError, match="min_rows"):
        asyncio.run(obj.amake(replace=True))


class _HTTPDBWithFailingCheck(_HTTPDB):
    id: ClassVar[str] = "ck_http_db_failing"
    checks: ClassVar[tuple[fb.Check, ...]] = (ck.MinRequests(1),)


def test_request_db_make_runs_checks_and_fails(test_local_data) -> None:
    """``RequestsDBMixin.make`` must run async checks at the end."""

    async def _go() -> None:
        db = _HTTPDBWithFailingCheck(_V.V1)
        # Force the "fresh populate" branch via replace=True so make()
        # tries to populate; our stub _populate_http_requests creates
        # zero HTTPRequest rows (just returns a UUID), so MinRequests(1)
        # is guaranteed to fire.
        with pytest.raises(ck.CheckFailedError, match="min_requests"):
            await db.make(replace=True)
        await db.close()

    asyncio.run(_go())


# =====================================================================
# Type / misuse guards
# =====================================================================


def test_table_check_on_composite_raises_typeerror(test_local_data) -> None:
    obj = _C(_V.V1)
    obj.make(replace=True)
    with pytest.raises(TypeError, match="MinRows requires Table"):
        ck.MinRows(1).run(obj)


def test_composite_check_on_table_raises_typeerror(test_local_data) -> None:
    obj = _T(_V.V1)
    obj.make(replace=True)
    with pytest.raises(TypeError, match="MinFiles requires Composite"):
        ck.MinFiles(1).run(obj)


def test_async_only_check_on_sync_make_raises(test_local_data) -> None:
    """Attaching an async-only check to a sync ``make()`` path surfaces clearly."""

    class _TAsyncCheckMisuse(fb.Table):
        id: ClassVar[str] = "ck_table_async_check_misuse"
        description: ClassVar[str] = "."
        supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
        row_schema: ClassVar[type[pyd.BaseModel]] = _TRow
        # MinRequests is async-only; sync make() can't run it.
        checks: ClassVar[tuple[fb.Check, ...]] = (ck.MinRequests(1),)

        @override
        def _make(self) -> None:
            self.save_arrow(pa.Table.from_pylist([{"city": "A", "n": 1}]))

    obj = _TAsyncCheckMisuse(_V.V1)
    with pytest.raises(NotImplementedError, match="async context"):
        obj.make(replace=True)

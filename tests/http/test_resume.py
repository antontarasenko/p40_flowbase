"""Tests for completion / resume semantics in ``RequestsDBMixin.make``.

``make()`` has three branches when ``replace=False``:

* **Complete** — rows exist, none pending, none failed (or ``retries == 0``):
  no-op.
* **Resume** — pending rows OR (``retries > 0`` and failed rows): skip
  populate; drive every group via unscoped ``execute`` / ``retry``.
* **Fresh** — no rows yet: populate a new group, then execute.
"""

import unittest.mock
import uuid
from datetime import (
    UTC,
    datetime,
)

import pytest
from sqlmodel import select

from p40_flowbase.http.models import (
    HTTPRequest,
    HTTPRequestGroup,
)


async def _execute_marker(_self, *args, **kwargs):
    """Replacement for ``_execute_pending_http_requests`` in tests.

    Marks every pending row as completed without making real HTTP calls.
    """
    async with _self.session_factory() as session:
        result = await session.exec(
            select(HTTPRequest).where(HTTPRequest.requested_at_utc.is_(None))  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        )
        rows = result.all()
        for row in rows:
            row.requested_at_utc = datetime.now(UTC)
            row.response_status = 200
            session.add(row)
        await session.commit()
    return list(rows)


class TestHTTPResume:
    @pytest.mark.asyncio
    async def test_resume_skips_populate_when_pending_rows_exist(self, http_db):
        # Seed a crashed prior run: one group + one pending row.
        group_id = uuid.uuid4()
        async with http_db.session_factory() as session:
            session.add(HTTPRequestGroup(http_request_group_id=group_id))
            session.add(
                HTTPRequest(
                    request_url="https://example.com/resume",
                    request_method="GET",
                    http_request_group_id=group_id,
                )
            )
            await session.commit()

        populate_mock = unittest.mock.AsyncMock(return_value=uuid.uuid4())
        http_db._populate_http_requests = populate_mock

        with unittest.mock.patch.object(
            type(http_db),
            "_execute_pending_http_requests",
            _execute_marker,
        ):
            await http_db.make(retries=0)

        assert populate_mock.await_count == 0

        async with http_db.session_factory() as session:
            groups = (
                await session.exec(select(HTTPRequestGroup))
            ).all()
            rows = (await session.exec(select(HTTPRequest))).all()

        assert len(groups) == 1
        assert len(rows) == 1
        assert rows[0].requested_at_utc is not None

    @pytest.mark.asyncio
    async def test_populates_fresh_when_no_pending_rows(self, http_db):
        new_group_id = uuid.uuid4()

        async def _fake_populate(self):
            async with self.session_factory() as session:
                session.add(HTTPRequestGroup(http_request_group_id=new_group_id))
                session.add(
                    HTTPRequest(
                        request_url="https://example.com/fresh",
                        request_method="GET",
                        http_request_group_id=new_group_id,
                    )
                )
                await session.commit()
            return new_group_id

        http_db._populate_http_requests = _fake_populate.__get__(http_db)

        with unittest.mock.patch.object(
            type(http_db),
            "_execute_pending_http_requests",
            _execute_marker,
        ):
            await http_db.make(retries=0)

        async with http_db.session_factory() as session:
            groups = (
                await session.exec(select(HTTPRequestGroup))
            ).all()
            rows = (await session.exec(select(HTTPRequest))).all()

        assert [g.http_request_group_id for g in groups] == [new_group_id]
        assert len(rows) == 1
        assert rows[0].requested_at_utc is not None

    @pytest.mark.asyncio
    async def test_skip_when_complete(self, http_db):
        # Seed a fully complete prior run: one group + one successful row.
        group_id = uuid.uuid4()
        completed_at = datetime.now(UTC)
        async with http_db.session_factory() as session:
            session.add(HTTPRequestGroup(http_request_group_id=group_id))
            session.add(
                HTTPRequest(
                    request_url="https://example.com/done",
                    request_method="GET",
                    http_request_group_id=group_id,
                    requested_at_utc=completed_at,
                    response_status=200,
                )
            )
            await session.commit()

        populate_mock = unittest.mock.AsyncMock(return_value=uuid.uuid4())
        execute_mock = unittest.mock.AsyncMock(return_value=[])
        retry_mock = unittest.mock.AsyncMock(return_value=[])
        http_db._populate_http_requests = populate_mock
        http_db._execute_pending_http_requests = execute_mock
        http_db._retry_failed_http_requests = retry_mock

        await http_db.make(retries=1)

        assert populate_mock.await_count == 0
        assert execute_mock.await_count == 0
        assert retry_mock.await_count == 0

        async with http_db.session_factory() as session:
            rows = (await session.exec(select(HTTPRequest))).all()

        assert len(rows) == 1
        assert rows[0].response_status == 200
        assert rows[0].requested_at_utc.replace(tzinfo=UTC) == completed_at

    @pytest.mark.asyncio
    async def test_retries_when_failed_rows_exist(self, http_db):
        # Seed a failed prior run: one group + one non-superseded failure.
        group_id = uuid.uuid4()
        async with http_db.session_factory() as session:
            session.add(HTTPRequestGroup(http_request_group_id=group_id))
            session.add(
                HTTPRequest(
                    request_url="https://example.com/boom",
                    request_method="GET",
                    http_request_group_id=group_id,
                    requested_at_utc=datetime.now(UTC),
                    response_status=500,
                )
            )
            await session.commit()

        populate_mock = unittest.mock.AsyncMock(return_value=uuid.uuid4())
        execute_mock = unittest.mock.AsyncMock(return_value=[])
        retry_mock = unittest.mock.AsyncMock(return_value=[])
        http_db._populate_http_requests = populate_mock
        http_db._execute_pending_http_requests = execute_mock
        http_db._retry_failed_http_requests = retry_mock

        await http_db.make(retries=3)

        assert populate_mock.await_count == 0
        assert execute_mock.await_count == 1
        assert retry_mock.await_count == 3

    @pytest.mark.asyncio
    async def test_skip_when_failed_rows_but_retries_zero(self, http_db):
        # With retries=0, failed rows do not count as "work to do".
        group_id = uuid.uuid4()
        async with http_db.session_factory() as session:
            session.add(HTTPRequestGroup(http_request_group_id=group_id))
            session.add(
                HTTPRequest(
                    request_url="https://example.com/boom",
                    request_method="GET",
                    http_request_group_id=group_id,
                    requested_at_utc=datetime.now(UTC),
                    response_status=500,
                )
            )
            await session.commit()

        populate_mock = unittest.mock.AsyncMock(return_value=uuid.uuid4())
        execute_mock = unittest.mock.AsyncMock(return_value=[])
        retry_mock = unittest.mock.AsyncMock(return_value=[])
        http_db._populate_http_requests = populate_mock
        http_db._execute_pending_http_requests = execute_mock
        http_db._retry_failed_http_requests = retry_mock

        await http_db.make(retries=0)

        assert populate_mock.await_count == 0
        assert execute_mock.await_count == 0
        assert retry_mock.await_count == 0

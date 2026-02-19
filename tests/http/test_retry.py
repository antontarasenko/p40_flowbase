import unittest.mock
import uuid
from datetime import (
    UTC,
    datetime,
)

import pytest
from sqlmodel import select

from p40_flowbase.http.models import HTTPRequest


class TestHTTPRetry:
    @pytest.mark.asyncio
    async def test_retry_creates_new_request_and_sets_superseded_by_id(
        self,
        http_db,
    ):
        failed_req = HTTPRequest(
            request_url="https://example.com",
            request_method="GET",
            response_status=500,
            requested_at_utc=datetime.now(UTC),
        )
        async with http_db.session_factory() as session:
            session.add(failed_req)
            await session.commit()
            await session.refresh(failed_req)

        original_id = failed_req.http_request_id
        new_id = uuid.uuid4()

        mock = unittest.mock.AsyncMock(
            return_value=HTTPRequest(
                http_request_id=new_id,
                request_url="https://example.com",
                request_method="GET",
                response_status=200,
            ),
        )

        with unittest.mock.patch.object(
            type(http_db),
            "_retry_single_http_request",
            mock,
        ):
            await http_db._retry_failed_http_requests()

        async with http_db.session_factory() as session:
            result = await session.exec(
                select(HTTPRequest).where(
                    HTTPRequest.http_request_id == original_id
                )
            )
            old_req = result.one()

        assert old_req.superseded_by_id == new_id

    @pytest.mark.asyncio
    async def test_retry_skips_already_superseded(self, http_db):
        already_superseded = HTTPRequest(
            request_url="https://example.com/a",
            request_method="GET",
            response_status=500,
            requested_at_utc=datetime.now(UTC),
            superseded_by_id=uuid.uuid4(),
        )
        not_superseded = HTTPRequest(
            request_url="https://example.com/b",
            request_method="GET",
            response_status=500,
            requested_at_utc=datetime.now(UTC),
        )
        async with http_db.session_factory() as session:
            session.add(already_superseded)
            session.add(not_superseded)
            await session.commit()
            await session.refresh(already_superseded)
            await session.refresh(not_superseded)

        new_id = uuid.uuid4()
        mock = unittest.mock.AsyncMock(
            return_value=HTTPRequest(
                http_request_id=new_id,
                request_url="https://example.com/b",
                request_method="GET",
                response_status=200,
            ),
        )

        with unittest.mock.patch.object(
            type(http_db),
            "_retry_single_http_request",
            mock,
        ):
            await http_db._retry_failed_http_requests()

        assert mock.call_count == 1

        async with http_db.session_factory() as session:
            result = await session.exec(
                select(HTTPRequest).where(
                    HTTPRequest.http_request_id == not_superseded.http_request_id
                )
            )
            req = result.one()
        assert req.superseded_by_id == new_id

    @pytest.mark.asyncio
    async def test_second_retry_does_not_re_retry_originals(self, http_db):
        failed_req = HTTPRequest(
            request_url="https://example.com",
            request_method="GET",
            response_status=500,
            requested_at_utc=datetime.now(UTC),
        )
        async with http_db.session_factory() as session:
            session.add(failed_req)
            await session.commit()
            await session.refresh(failed_req)

        original_id = failed_req.http_request_id
        first_retry_id = uuid.uuid4()
        mock = unittest.mock.AsyncMock(
            return_value=HTTPRequest(
                http_request_id=first_retry_id,
                request_url="https://example.com",
                request_method="GET",
                response_status=200,
            ),
        )

        with unittest.mock.patch.object(
            type(http_db),
            "_retry_single_http_request",
            mock,
        ):
            await http_db._retry_failed_http_requests()
            assert mock.call_count == 1

            mock.reset_mock()
            await http_db._retry_failed_http_requests()
            assert mock.call_count == 0

        async with http_db.session_factory() as session:
            result = await session.exec(
                select(HTTPRequest).where(
                    HTTPRequest.http_request_id == original_id
                )
            )
            old_req = result.one()

        assert old_req.superseded_by_id == first_retry_id

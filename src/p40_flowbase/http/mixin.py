"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
import time
import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    override,
)

from p40_flowbase.core.requests_mixin import RequestsDBMixin
from p40_flowbase.http.models import HTTPRequest
from p40_flowbase.logging import logger

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from sqlalchemy.sql.elements import ColumnElement


class HTTPDB(RequestsDBMixin[HTTPRequest]):
    """DB for logging and retrying HTTP requests.

    Subclasses should set ``tables`` to include at least ``HTTPRequestGroup``
    and ``HTTPRequest`` (plus optionally ``HTTPRequestExtra``), and implement
    ``_populate_http_requests() -> uuid.UUID`` to create the initial request
    rows.
    """

    rate_limit: ClassVar[float] = 5.0
    rate_period: ClassVar[float] = 1.0

    _request_model: ClassVar[type[Any] | None] = HTTPRequest
    _pending_column: ClassVar[str | None] = "requested_at_utc"

    @classmethod
    @override
    def _failed_predicate(cls) -> "ColumnElement[bool] | None":
        from sqlalchemy import and_

        return and_(
            HTTPRequest.response_status != 200,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
            HTTPRequest.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        )

    @override
    async def _populate(self) -> uuid.UUID:
        if not hasattr(self, "_populate_http_requests"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement "
                "_populate_http_requests() method"
            )
        result: uuid.UUID = await self._populate_http_requests()  # pyright: ignore[reportAttributeAccessIssue]
        return result

    @override
    async def _execute_pending(
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 5.0,
        rate_period: float = 1.0,
    ) -> list[HTTPRequest]:
        return await self._execute_pending_http_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            http_request_group_id=str(group_id) if group_id else None,
        )

    @override
    async def _retry_failed(
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 5.0,
        rate_period: float = 1.0,
    ) -> list[HTTPRequest]:
        return await self._retry_failed_http_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            http_request_group_id=str(group_id) if group_id else None,
        )

    @override
    async def _get_wave_results(
        self,
        group_id: uuid.UUID,
    ) -> list[HTTPRequest]:
        return await self._get_http_wave_results(group_id=group_id)

    async def _add_http_requests(
        self,
        requests: list[dict[str, Any]],
    ) -> list[HTTPRequest]:
        """Add HTTP requests to the database for later execution."""
        created_logs = []

        async with self.session_factory() as session:
            for request_data in requests:
                log_entry = HTTPRequest(
                    request_url=request_data["request_url"],
                    request_method=request_data["request_method"],
                    request_headers=request_data.get("request_headers"),
                    request_body=request_data.get("request_body"),
                    http_request_group_id=request_data.get("http_request_group_id"),
                    http_request_extra_id=request_data.get("http_request_extra_id"),
                )
                session.add(log_entry)
                created_logs.append(log_entry)

            await session.commit()

            for log_entry in created_logs:
                await session.refresh(log_entry)

        return created_logs

    async def _execute_http_request(
        self,
        http_client: "ClientSession",
        request_method: str,
        request_url: str,
        request_headers: str | None,
        request_body: str | None,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a single HTTP request and return response data."""
        requested_at_utc = datetime.now(UTC)
        start_time = time.monotonic()

        request_options: dict[str, Any] = {}

        headers: dict[str, str] = {}
        if request_headers:
            headers.update(json.loads(request_headers))
        if ephemeral_headers:
            headers.update(ephemeral_headers)

        if headers:
            request_options["headers"] = headers

        if request_body:
            request_options["data"] = request_body

        response = await http_client.request(
            method=request_method,
            url=request_url,
            **request_options,
        )
        response_body = await response.read()

        return {
            "response_status": response.status,
            "response_headers": json.dumps(dict(response.headers)),
            "response_body_text": response_body.decode(errors="replace"),
            "response_size": len(response_body),
            "latency": time.monotonic() - start_time,
            "requested_at_utc": requested_at_utc,
        }

    async def _execute_pending_http_requests(
        self,
        rate_limit: float = 5.0,
        rate_period: float = 1.0,
        ephemeral_headers: dict[str, str] | None = None,
        http_request_group_id: str | None = None,
    ) -> list[HTTPRequest]:
        """Execute all HTTP requests where ``requested_at_utc`` is null."""
        import aiohttp
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(HTTPRequest).where(
                HTTPRequest.requested_at_utc.is_(None)  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            if http_request_group_id is not None:
                group_uuid = uuid.UUID(http_request_group_id)
                statement = statement.where(
                    HTTPRequest.http_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            rows = result.all()

        async with aiohttp.ClientSession() as http_client:
            async def execute_one(row: HTTPRequest) -> HTTPRequest:
                return await self._process_single_http_request(
                    http_client,
                    row,
                    ephemeral_headers,
                )

            return await self._run_batch(
                rows=list(rows),
                execute_one=execute_one,
                rate_limit=rate_limit,
                rate_period=rate_period,
                is_success=lambda r: r.response_status == 200,
                label="HTTP request",
            )

    async def _process_single_http_request(
        self,
        http_client: "ClientSession",
        row: HTTPRequest,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> HTTPRequest:
        """Execute ``row`` and persist the response on the same row."""
        response_data = await self._execute_http_request(
            http_client=http_client,
            request_method=row.request_method,
            request_url=row.request_url,
            request_headers=row.request_headers,
            request_body=row.request_body,
            ephemeral_headers=ephemeral_headers,
        )

        async with self.session_factory() as session:
            for key, value in response_data.items():
                setattr(row, key, value)

            session.add(row)
            await session.commit()
            await session.refresh(row)

        if row.response_status != 200:
            logger.error(
                f"HTTP request failed with status {row.response_status} "
                f"(http_request_id: {row.http_request_id}, "
                f"url: {row.request_url}). "
                f"Response body: {row.response_body_text}"
            )

        return row

    async def _retry_single_http_request(
        self,
        http_client: "ClientSession",
        row: HTTPRequest,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> HTTPRequest:
        """Retry a failed request by inserting a new row with the new response."""
        response_data = await self._execute_http_request(
            http_client=http_client,
            request_method=row.request_method,
            request_url=row.request_url,
            request_headers=row.request_headers,
            request_body=row.request_body,
            ephemeral_headers=ephemeral_headers,
        )

        new_log = HTTPRequest(
            request_url=row.request_url,
            request_method=row.request_method,
            request_headers=row.request_headers,
            request_body=row.request_body,
            http_request_group_id=row.http_request_group_id,
            http_request_extra_id=row.http_request_extra_id,
            created_at_utc=datetime.now(UTC),
            **response_data,
        )

        async with self.session_factory() as session:
            session.add(new_log)
            await session.commit()
            await session.refresh(new_log)

        return new_log

    async def _retry_failed_http_requests(
        self,
        rate_limit: float = 5.0,
        rate_period: float = 1.0,
        ephemeral_headers: dict[str, str] | None = None,
        http_request_group_id: str | None = None,
    ) -> list[HTTPRequest]:
        """Retry all HTTP requests with response_status != 200."""
        import aiohttp
        import sqlalchemy
        from sqlmodel import select

        from p40_flowbase.helpers.rate_limit import create_limiter

        limiter = create_limiter(rate_limit, rate_period)

        async with self.session_factory() as session:
            statement = select(HTTPRequest).where(
                HTTPRequest.response_status != 200,  # pyright: ignore[reportArgumentType]
                HTTPRequest.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            if http_request_group_id is not None:
                group_uuid = uuid.UUID(http_request_group_id)
                statement = statement.where(
                    HTTPRequest.http_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            rows = result.all()

        async with aiohttp.ClientSession() as http_client:
            for row in rows:
                try:
                    async with limiter:
                        new_request = await self._retry_single_http_request(
                            http_client,
                            row,
                            ephemeral_headers,
                        )
                    async with self.session_factory() as session:
                        await session.exec(
                            sqlalchemy.update(HTTPRequest)
                            .where(
                                HTTPRequest.http_request_id  # type: ignore[arg-type]
                                == row.http_request_id  # pyright: ignore[reportArgumentType]
                            )
                            .values(
                                superseded_by_id=new_request.http_request_id
                            )
                        )
                        await session.commit()
                except Exception as e:  # noqa: BLE001  # log per-request retry failure; keep batch going
                    logger.error(
                        f"HTTP retry failed for request {row.http_request_id}: {e}"
                    )
                    continue

        return list(rows)

    async def _get_http_wave_results(
        self,
        group_id: uuid.UUID,
    ) -> list[HTTPRequest]:
        """Return non-superseded HTTP requests for ``group_id``."""
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(HTTPRequest).where(
                HTTPRequest.http_request_group_id == group_id,
                HTTPRequest.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            result = await session.exec(statement)
            return list(result.all())

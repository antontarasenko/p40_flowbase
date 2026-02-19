"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
import json
import time
import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from p40_flowbase.http.models import HTTPRequest
from p40_flowbase.logging import logger


class HTTPRequestsDBMixin:
    """Mixin for logging and retrying HTTP requests.

    Classes using this mixin must include HTTPRequestGroup and HTTPRequest
    in their schema attribute. Optionally include HTTPRequestExtra for
    per-request custom metadata.

    Subclasses should implement:
        - async def _populate_http_requests(self) -> uuid.UUID:
            Create and add HTTP requests, return the group_id.
    """

    async def populate(self) -> uuid.UUID:
        """Populate HTTP requests based on object version and configuration.

        Returns:
            UUID of the created request group.
        """
        if not hasattr(self, "_populate_http_requests"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement _populate_http_requests() method"
            )
        return await self._populate_http_requests()

    async def execute(
        self,
        group_id: Optional[uuid.UUID] = None,
        rate_limit: float = 5.0,
        rate_period: float = 1.0,
    ):
        """Execute pending HTTP requests.

        Args:
            group_id: If provided, only execute requests from this group.
            rate_limit: Maximum requests per rate_period.
            rate_period: Time period in seconds for rate limiting.

        Returns:
            List of executed request entries.
        """
        return await self._execute_pending_http_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            http_request_group_id=str(group_id) if group_id else None,
        )

    async def retry(
        self,
        group_id: Optional[uuid.UUID] = None,
        rate_limit: float = 5.0,
        rate_period: float = 1.0,
    ):
        """Retry failed HTTP requests.

        Args:
            group_id: If provided, only retry requests from this group.
            rate_limit: Maximum requests per rate_period.
            rate_period: Time period in seconds for rate limiting.

        Returns:
            List of retried request entries.
        """
        return await self._retry_failed_http_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            http_request_group_id=str(group_id) if group_id else None,
        )

    async def _add_http_requests(
        self,
        requests: List[Dict[str, Any]],
    ) -> List[HTTPRequest]:
        """Add HTTP requests to the database for later execution.

        Args:
            requests: List of dicts with request fields. Each dict should contain:
                - request_url (str): URL to request
                - request_method (str): HTTP method (GET, POST, etc.)
                - request_headers (Optional[str]): JSON string of headers
                - request_body (Optional[str]): Request body
                - http_request_group_id (Optional[uuid.UUID]): Reference to request group
                - http_request_extra_id (Optional[uuid.UUID]): Reference to request extra metadata

        Returns:
            List of created HTTPRequest entries.
        """
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
        http_client,
        request_method: str,
        request_url: str,
        request_headers: Optional[str],
        request_body: Optional[str],
        ephemeral_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute a single HTTP request and return response data.

        Args:
            http_client: aiohttp.ClientSession instance.
            request_method: HTTP method (GET, POST, etc.).
            request_url: URL to request.
            request_headers: JSON string of headers or None.
            request_body: Request body string or None.
            ephemeral_headers: Headers to include in request but not store in database.

        Returns:
            Dict containing response_status, response_headers, response_body_text,
            response_size, latency, and requested_at_utc.
        """
        requested_at_utc = datetime.now(UTC)
        start_time = time.monotonic()

        request_options = {}

        headers = {}
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
        ephemeral_headers: Optional[Dict[str, str]] = None,
        http_request_group_id: Optional[str] = None,
    ):
        """Execute all requests where requested_at_utc is null.

        Args:
            rate_limit: Maximum number of requests per rate_period.
            rate_period: Time period in seconds for rate limiting.
            ephemeral_headers: Headers to include in requests but not store in database.
            http_request_group_id: If provided, only process requests from this group.

        Returns:
            List of executed request entries with responses populated.
        """
        import aiohttp
        from aiolimiter import AsyncLimiter
        from sqlmodel import select

        limiter = AsyncLimiter(max_rate=rate_limit, time_period=rate_period)

        async with self.session_factory() as session:
            statement = select(HTTPRequest).where(
                HTTPRequest.requested_at_utc.is_(None)
            )
            if http_request_group_id is not None:
                group_uuid = (
                    uuid.UUID(http_request_group_id)
                    if isinstance(http_request_group_id, str)
                    else http_request_group_id
                )
                statement = statement.where(
                    HTTPRequest.http_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            rows = result.all()

        async with aiohttp.ClientSession() as http_client:

            async def rate_limited_request(row):
                async with limiter:
                    pass
                return await self._process_single_http_request(
                    http_client,
                    row,
                    ephemeral_headers,
                )

            tasks = [rate_limited_request(row) for row in rows]

            executed = []
            successful_count = 0
            failed_count = 0
            start_time = time.time()

            for completed_task in asyncio.as_completed(tasks):
                result = await completed_task
                executed.append(result)

                if result.response_status == 200:
                    successful_count += 1
                else:
                    failed_count += 1

                if len(executed) % 100 == 0:
                    elapsed = time.time() - start_time
                    effective_rps = len(executed) / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Progress: {len(executed)} completed "
                        f"({successful_count} succeeded, {failed_count} failed), "
                        f"{elapsed:.1f}s elapsed, {effective_rps:.2f} RPS"
                    )

            elapsed = time.time() - start_time
            effective_rps = len(executed) / elapsed if elapsed > 0 else 0
            logger.info(
                f"Completed processing {len(executed)} HTTP requests: "
                f"{successful_count} succeeded, {failed_count} failed, "
                f"{elapsed:.1f}s total, {effective_rps:.2f} RPS"
            )

        return executed

    async def _process_single_http_request(
        self,
        http_client,
        row: HTTPRequest,
        ephemeral_headers: Optional[Dict[str, str]] = None,
    ) -> HTTPRequest:
        """Process a single HTTP request.

        Args:
            http_client: aiohttp ClientSession instance.
            row: HTTP request to execute.
            ephemeral_headers: Headers to include but not store in database.

        Returns:
            Updated HTTP request with response populated.
        """
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
                f"(http_request_id: {row.http_request_id}, url: {row.request_url}). "
                f"Response body: {row.response_body_text}"
            )

        return row

    async def _retry_single_http_request(
        self,
        http_client,
        row: HTTPRequest,
        ephemeral_headers: Optional[Dict[str, str]] = None,
    ) -> HTTPRequest:
        """Retry a single failed HTTP request and create a new log entry.

        Args:
            http_client: aiohttp ClientSession instance.
            row: Failed HTTP request to retry.
            ephemeral_headers: Headers to include but not store in database.

        Returns:
            New HTTPRequest entry with retry response.
        """
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
        ephemeral_headers: Optional[Dict[str, str]] = None,
        http_request_group_id: Optional[str] = None,
    ):
        """Retry all requests that did not return status 200.

        Args:
            rate_limit: Maximum number of requests per rate_period.
            rate_period: Time period in seconds for rate limiting.
            ephemeral_headers: Headers to include in requests but not store in database.
            http_request_group_id: If provided, only process requests from this group.

        Returns:
            List of original failed request entries that were retried.
        """
        import aiohttp
        import sqlalchemy
        from aiolimiter import AsyncLimiter
        from sqlmodel import select

        limiter = AsyncLimiter(max_rate=rate_limit, time_period=rate_period)

        async with self.session_factory() as session:
            statement = select(HTTPRequest).where(
                HTTPRequest.response_status != 200,
                HTTPRequest.superseded_by_id.is_(None),
            )
            if http_request_group_id is not None:
                group_uuid = (
                    uuid.UUID(http_request_group_id)
                    if isinstance(http_request_group_id, str)
                    else http_request_group_id
                )
                statement = statement.where(
                    HTTPRequest.http_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            rows = result.all()

        async with aiohttp.ClientSession() as http_client:
            for row in rows:
                async with limiter:
                    new_request = await self._retry_single_http_request(
                        http_client,
                        row,
                        ephemeral_headers,
                    )
                async with self.session_factory() as session:
                    await session.execute(
                        sqlalchemy.update(HTTPRequest)
                        .where(
                            HTTPRequest.http_request_id == row.http_request_id
                        )
                        .values(superseded_by_id=new_request.http_request_id)
                    )
                    await session.commit()

        return rows

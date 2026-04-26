"""
MIT License

Copyright (c) 2025 Anton Tarasenko

Generic per-host coordinator for rate-limited retries against a single
upstream service that occasionally goes down service-wide (e.g. the Wayback
Machine). Encapsulates:

- Rate limiting under an ``asyncio.Lock``
- Exponential backoff with a configurable ceiling
- Shared "give up" threshold once cumulative outage exceeds ``max_outage``
- Epoch-based backoff increments so parallel workers don't pile on each
  other when the same outage is observed concurrently
- Classification of "server-wide" status codes vs. page-specific ones

Usage sketch:

    coord = HostCoordinator(rate_period=20.0, max_outage=10800.0)

    if coord.is_unavailable:
        if not await coord.wait_for_availability():
            return False  # gave up

    epoch = coord.backoff_epoch
    async with coord.rate_limited():
        response = await do_request()

    if coord.is_server_error(response.status):
        coord.set_backoff(epoch)
        if not await coord.wait_for_availability():
            return False
    else:
        coord.reset_on_success()
"""

import asyncio
import time
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from p40_flowbase.logging import logger


@dataclass(frozen=True, slots=True)
class CoordinatorState:
    """Snapshot of a ``HostCoordinator``'s internal bookkeeping.

    Stable; intended for tests and diagnostic logging. Do not mutate the
    coordinator via this snapshot — it is a read-only view captured at the
    moment ``HostCoordinator.state`` was accessed.
    """

    unavailable_until: float
    outage_start: float
    backoff_step: int
    backoff_epoch: int
    last_request_time: float


class HostCoordinator:
    """Coordinate rate-limited retries against a single host.

    Args:
        rate_period: Minimum seconds between consecutive requests.
        server_error_codes: Status codes treated as server-wide outages.
            Defaults to ``{429, 502, 503, 504}``. ``None`` response statuses
            (connection errors) are always treated as server-wide.
        max_outage: Maximum cumulative outage seconds before giving up.
        base_backoff: Initial backoff duration in seconds.
        max_backoff: Ceiling for exponential backoff in seconds.
        name: Human-readable label used in log messages.
    """

    def __init__(
        self,
        rate_period: float = 1.0,
        server_error_codes: Iterable[int] | None = None,
        max_outage: float = 86400.0,
        base_backoff: float = 60.0,
        max_backoff: float = 3840.0,
        name: str = "host",
    ) -> None:
        self.rate_period = rate_period
        self.server_error_codes: set[int] = set(
            server_error_codes if server_error_codes is not None else {429, 502, 503, 504}
        )
        self.max_outage = max_outage
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.name = name

        self._unavailable_until: float = 0.0
        self._outage_start: float = 0.0
        self._backoff_step: int = 0
        self._backoff_epoch: int = 0
        self._last_request_time: float = 0.0

        self._availability_lock: asyncio.Lock = asyncio.Lock()
        self._request_lock: asyncio.Lock = asyncio.Lock()

    @property
    def state(self) -> CoordinatorState:
        """Snapshot of internal state for tests and diagnostics."""
        return CoordinatorState(
            unavailable_until=self._unavailable_until,
            outage_start=self._outage_start,
            backoff_step=self._backoff_step,
            backoff_epoch=self._backoff_epoch,
            last_request_time=self._last_request_time,
        )

    @property
    def backoff_epoch(self) -> int:
        """Return the current backoff epoch.

        Call sites should capture this value *before* making a request and
        pass it to ``set_backoff`` so concurrent workers observing the same
        outage don't each increment the backoff.
        """
        return self._backoff_epoch

    @property
    def is_unavailable(self) -> bool:
        """Return True if the host is currently in a backoff window."""
        return self._unavailable_until > time.monotonic()

    def is_server_error(self, response_status: int | None) -> bool:
        """Classify a response status as a server-wide error.

        A ``None`` status (connection error / no response) always counts as
        server-wide.
        """
        if response_status is None:
            return True
        return response_status in self.server_error_codes

    async def wait_for_availability(self) -> bool:
        """Sleep until the current backoff window expires.

        Returns:
            True if the caller should retry,
            False if cumulative outage exceeded ``max_outage`` (give up).
        """
        now = time.monotonic()
        sleep_duration = self._unavailable_until - now
        if sleep_duration > 0:
            logger.info(
                f"{self.name} unavailable, sleeping {sleep_duration:.0f}s..."
            )
            await asyncio.sleep(sleep_duration)

        async with self._availability_lock:
            if self._unavailable_until == 0.0:
                return True

            if (
                self._outage_start > 0.0
                and time.monotonic() - self._outage_start > self.max_outage
            ):
                logger.error(
                    f"{self.name} unavailable for "
                    f"{time.monotonic() - self._outage_start:.0f}s, giving up"
                )
                return False

            logger.info(f"{self.name} backoff expired, retrying request...")
            return True

    def set_backoff(self, epoch_before: int) -> None:
        """Increment backoff if no other lane already did so for this epoch.

        Call with the value of ``backoff_epoch`` captured *before* the
        failing request. If another concurrent worker already incremented
        the epoch (meaning they already set the backoff for the outage we
        just observed), this is a no-op.
        """
        if self._backoff_epoch != epoch_before:
            return
        if self._outage_start == 0.0:
            self._outage_start = time.monotonic()
        backoff = min(
            self.base_backoff * (2 ** self._backoff_step),
            self.max_backoff,
        )
        self._backoff_step += 1
        self._backoff_epoch += 1
        self._unavailable_until = time.monotonic() + backoff
        logger.info(
            f"{self.name} backoff set to {backoff:.0f}s "
            f"(step {self._backoff_step})"
        )

    def reset_on_success(self) -> None:
        """Clear outage state after a successful response."""
        self._unavailable_until = 0.0
        self._outage_start = 0.0
        self._backoff_step = 0
        self._backoff_epoch = 0

    @asynccontextmanager
    async def rate_limited(self) -> AsyncIterator[None]:
        """Enter a rate-limited critical section serialized by an asyncio lock.

        Sleeps before yielding if needed so that consecutive requests are at
        least ``rate_period`` seconds apart. The last-request timestamp is
        recorded on exit (success or exception).
        """
        async with self._request_lock:
            if self._last_request_time > 0:
                elapsed = time.monotonic() - self._last_request_time
                if elapsed < self.rate_period:
                    delay = self.rate_period - elapsed
                    logger.info(
                        f"{self.name} rate limit: waiting {delay:.1f}s "
                        "before next request"
                    )
                    await asyncio.sleep(delay)
            try:
                yield
            finally:
                self._last_request_time = time.monotonic()

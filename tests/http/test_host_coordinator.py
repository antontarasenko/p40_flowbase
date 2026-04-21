"""Tests for HostCoordinator."""

import asyncio
import time

import pytest

from p40_flowbase.http.host_coordinator import HostCoordinator


class TestHostCoordinatorClassification:
    def test_none_status_is_server_error(self):
        coord = HostCoordinator()
        assert coord.is_server_error(None) is True

    def test_200_is_not_server_error(self):
        coord = HostCoordinator()
        assert coord.is_server_error(200) is False

    def test_404_is_not_server_error_by_default(self):
        coord = HostCoordinator()
        assert coord.is_server_error(404) is False

    def test_default_server_error_codes(self):
        coord = HostCoordinator()
        assert coord.is_server_error(429) is True
        assert coord.is_server_error(502) is True
        assert coord.is_server_error(503) is True
        assert coord.is_server_error(504) is True

    def test_custom_server_error_codes(self):
        coord = HostCoordinator(server_error_codes={500, 503})
        assert coord.is_server_error(500) is True
        assert coord.is_server_error(503) is True
        assert coord.is_server_error(429) is False


class TestHostCoordinatorBackoff:
    def test_initial_state_is_available(self):
        coord = HostCoordinator()
        assert coord.is_unavailable is False
        assert coord.backoff_epoch == 0

    def test_set_backoff_increments_epoch(self):
        coord = HostCoordinator(base_backoff=60.0)
        epoch_before = coord.backoff_epoch
        coord.set_backoff(epoch_before)
        assert coord.backoff_epoch == epoch_before + 1
        assert coord.is_unavailable is True

    def test_set_backoff_ignored_on_stale_epoch(self):
        coord = HostCoordinator(base_backoff=60.0)
        epoch_before = coord.backoff_epoch
        coord.set_backoff(epoch_before)
        # A second lane captured the same stale epoch; must be a no-op.
        prev_unavailable_until = coord._unavailable_until
        coord.set_backoff(epoch_before)
        assert coord.backoff_epoch == epoch_before + 1
        assert coord._unavailable_until == prev_unavailable_until

    def test_exponential_backoff_growth(self):
        coord = HostCoordinator(base_backoff=10.0, max_backoff=1_000_000.0)
        coord.set_backoff(0)
        first_window = coord._unavailable_until - time.monotonic()
        coord.set_backoff(1)
        second_window = coord._unavailable_until - time.monotonic()
        coord.set_backoff(2)
        third_window = coord._unavailable_until - time.monotonic()
        assert 9 < first_window < 11
        assert 19 < second_window < 21
        assert 39 < third_window < 41

    def test_backoff_capped_at_max(self):
        coord = HostCoordinator(base_backoff=100.0, max_backoff=150.0)
        coord.set_backoff(0)
        coord.set_backoff(1)
        coord.set_backoff(2)
        window = coord._unavailable_until - time.monotonic()
        assert window <= 150.0 + 0.5

    def test_reset_on_success_clears_state(self):
        coord = HostCoordinator(base_backoff=60.0)
        coord.set_backoff(0)
        assert coord.is_unavailable is True
        coord.reset_on_success()
        assert coord.is_unavailable is False
        assert coord.backoff_epoch == 0
        assert coord._backoff_step == 0
        assert coord._outage_start == 0.0


class TestHostCoordinatorWaitForAvailability:
    @pytest.mark.asyncio
    async def test_returns_true_immediately_when_available(self):
        coord = HostCoordinator()
        assert await coord.wait_for_availability() is True

    @pytest.mark.asyncio
    async def test_gives_up_past_max_outage(self):
        coord = HostCoordinator(base_backoff=0.01, max_outage=0.05)
        coord.set_backoff(0)
        await asyncio.sleep(0.02)
        coord.set_backoff(1)
        await asyncio.sleep(0.1)
        result = await coord.wait_for_availability()
        assert result is False


class TestHostCoordinatorRateLimited:
    @pytest.mark.asyncio
    async def test_first_request_has_no_delay(self):
        coord = HostCoordinator(rate_period=1.0)
        start = time.monotonic()
        async with coord.rate_limited():
            pass
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_consecutive_requests_are_spaced(self):
        coord = HostCoordinator(rate_period=0.2)
        async with coord.rate_limited():
            pass
        start = time.monotonic()
        async with coord.rate_limited():
            pass
        elapsed = time.monotonic() - start
        assert 0.15 < elapsed < 0.35

    @pytest.mark.asyncio
    async def test_rate_limited_serializes_concurrent_callers(self):
        coord = HostCoordinator(rate_period=0.1)

        async def do_request():
            async with coord.rate_limited():
                return time.monotonic()

        results = await asyncio.gather(*[do_request() for _ in range(3)])
        results.sort()
        assert results[1] - results[0] >= 0.08
        assert results[2] - results[1] >= 0.08

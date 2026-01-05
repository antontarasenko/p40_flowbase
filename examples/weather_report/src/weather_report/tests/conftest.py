"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import matplotlib
import pytest

import p40_flowbase as fb
import weather_report.config as config

matplotlib.use("Agg")


@pytest.fixture(scope="session", autouse=True)
def test_data_local_tmp(tmp_path_factory):
    """Override config.settings.data_local_tmp to use a temporary directory for tests.

    This ensures test data is isolated from production/development data.
    The fixture is session-scoped and applies automatically to all tests.
    """
    test_tmp_dir = tmp_path_factory.mktemp("test_data")
    original_data_local_tmp = config.settings.data_local_tmp
    config.settings.data_local_tmp = str(test_tmp_dir)
    fb.DataObject.set_data_local_tmp(str(test_tmp_dir))

    yield test_tmp_dir

    config.settings.data_local_tmp = original_data_local_tmp
    if original_data_local_tmp:
        fb.DataObject.set_data_local_tmp(original_data_local_tmp)


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as async (requires pytest-asyncio)",
    )
    config.addinivalue_line(
        "markers",
        "serial: mark test to run serially (not in parallel with pytest-xdist)",
    )


def pytest_collection_modifyitems(items):
    """Modify test collection to handle serial tests with pytest-xdist.

    Tests marked with @pytest.mark.serial will run sequentially
    even when using pytest-xdist parallel execution.
    """
    for item in items:
        if "serial" in item.keywords:
            item.add_marker(pytest.mark.xdist_group(name="serial"))


@pytest.fixture(scope="session")
def weather_http_requests_db(test_data_local_tmp):
    """Fixture that ensures WeatherHTTPRequestsDB exists in test environment.

    Creates a fresh database for each test session and populates it with sample data
    for EAST_COAST version. This fixture must be used instead of skipif decorators
    because those are evaluated at import time before test_data_local_tmp
    fixture runs.

    With pytest-xdist, this fixture is created once per worker, ensuring each
    worker has its own isolated database.
    """
    import asyncio

    from weather_report.data import (
        CitySample,
        CoastVersions,
        MainVersions,
        WeatherHTTPRequestsDB,
    )

    db = WeatherHTTPRequestsDB(MainVersions.MAIN)

    asyncio.run(db.make_async(replace=True))

    sample = CitySample(CoastVersions.EAST_COAST)
    sample.make(replace=True)

    async def populate_all():
        await db.populate()
        await db.execute(rate_limit=5.0, rate_period=1.0)

        await db._populate_forecast_requests(CoastVersions.EAST_COAST)
        await db.execute(rate_limit=5.0, rate_period=1.0)

    asyncio.run(populate_all())

    return db

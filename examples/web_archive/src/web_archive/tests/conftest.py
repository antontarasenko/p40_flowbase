"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import matplotlib
import pytest

import p40_flowbase as fb
import web_archive.config as config

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
def wm_snapshot_urls_db(test_data_local_tmp):
    """Fixture that ensures WMSnapshotURLsDB exists in test environment.

    Creates a fresh database for each test session and populates it with sample data
    for UNIS_1_TEST version. This fixture must be used instead of skipif decorators
    because those are evaluated at import time before test_data_local_tmp
    fixture runs.

    With pytest-xdist, this fixture is created once per worker, ensuring each
    worker has its own isolated database.
    """
    import asyncio

    from web_archive.data import (
        URLSample,
        URLVersions,
        WMSnapshotURLsDB,
    )

    sample = URLSample(URLVersions.UNIS_1_TEST)
    sample.make(replace=True)

    db = WMSnapshotURLsDB(URLVersions.UNIS_1_TEST)

    asyncio.run(db.make_async(replace=True))

    async def populate_all():
        await db.populate()
        await db.execute(rate_limit=5.0, rate_period=1.0)

    asyncio.run(populate_all())

    return db


@pytest.fixture(scope="session")
def wm_snapshot_content_db(wm_snapshot_urls_db, test_data_local_tmp):
    """Fixture that ensures WMSnapshotContentDB exists in test environment.

    Creates a fresh database for each test session and populates it with sample data
    for UNIS_1_TEST version. Depends on wm_snapshot_urls_db to ensure URL data exists.
    """
    import asyncio

    from web_archive.data import (
        URLVersions,
        WMSnapshotContentDB,
        WMSnapshotURLs,
    )

    urls_table = WMSnapshotURLs(URLVersions.UNIS_1_TEST)
    urls_table.make(replace=True)

    db = WMSnapshotContentDB(URLVersions.UNIS_1_TEST)

    asyncio.run(db.make_async(replace=True))

    async def populate_all():
        await db.populate()
        await db.execute(rate_limit=5.0, rate_period=1.0)

    asyncio.run(populate_all())

    return db

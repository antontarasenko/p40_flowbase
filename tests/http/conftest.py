from enum import Enum

import pytest

from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.database import DBDataObject
from p40_flowbase.http.mixin import HTTPRequestsDBMixin
from p40_flowbase.http.models import (
    HTTPRequest,
    HTTPRequestGroup,
)


class TestVersion(Enum):
    V1 = DataObjectVersion(
        id="test",
        name="Test",
        description="Test version",
    )


class TestHTTPDB(HTTPRequestsDBMixin, DBDataObject):
    """Minimal DB object for testing HTTP retry logic."""

    id = "test_http"
    description = "Test HTTP DB"
    supported_versions = (TestVersion.V1,)
    schema = [HTTPRequestGroup, HTTPRequest]


@pytest.fixture
async def http_db(test_data_local_tmp):
    db = TestHTTPDB(TestVersion.V1)
    await db.make_async(replace=True)
    yield db
    await db.close()

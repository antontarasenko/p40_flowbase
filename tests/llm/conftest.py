from enum import Enum

import pytest

from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.database import DBDataObject
from p40_flowbase.http.mixin import HTTPRequestsDBMixin
from p40_flowbase.http.models import (
    HTTPRequest,
    HTTPRequestGroup,
)
from p40_flowbase.llm.mixin import LLMRequestsDBMixin
from p40_flowbase.llm.models import (
    LLMRequest,
    LLMRequestGroup,
)


class TestVersion(Enum):
    V1 = DataObjectVersion(
        id="test",
        name="Test",
        description="Test version",
    )


class TestLLMDB(LLMRequestsDBMixin, HTTPRequestsDBMixin, DBDataObject):
    """Minimal DB object for testing LLM retry logic."""

    id = "test_llm"
    description = "Test LLM DB"
    supported_versions = (TestVersion.V1,)
    schema = [HTTPRequestGroup, HTTPRequest, LLMRequestGroup, LLMRequest]


@pytest.fixture
async def llm_db(test_data_local_tmp):
    db = TestLLMDB(TestVersion.V1)
    await db.make_async(replace=True)
    yield db
    await db.close()

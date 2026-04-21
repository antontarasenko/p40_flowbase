from enum import Enum

import pytest

from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.http.models import (
    HTTPRequest,
    HTTPRequestGroup,
)
from p40_flowbase.llm.mixin import LLMDB
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


class TestLLMDB(LLMDB):
    """Minimal DB object for testing LLM retry logic."""

    id = "test_llm"
    description = "Test LLM DB"
    supported_versions = (TestVersion.V1,)
    tables = [HTTPRequestGroup, HTTPRequest, LLMRequestGroup, LLMRequest]


@pytest.fixture
async def llm_db(test_local_data):
    db = TestLLMDB(TestVersion.V1)
    await db.create_tables(replace=True)
    yield db
    await db.close()

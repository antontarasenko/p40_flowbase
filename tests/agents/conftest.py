from enum import Enum

import pytest

from p40_flowbase.agents.mixin import AgentDB
from p40_flowbase.agents.models import (
    AgentTask,
    AgentTaskGroup,
)
from p40_flowbase.core.base import DataObjectVersion


class TestVersion(Enum):
    V1 = DataObjectVersion(
        id="test",
        name="Test",
        description="Test version",
    )


class TestAgentDB(AgentDB):
    """Minimal DB object for testing agent retry logic."""

    id = "test_agent"
    description = "Test Agent DB"
    supported_versions = (TestVersion.V1,)
    tables = [AgentTaskGroup, AgentTask]


@pytest.fixture
async def agent_db(test_local_data):
    db = TestAgentDB(TestVersion.V1)
    await db.create_tables(replace=True)
    yield db
    await db.close()

from enum import Enum

import pytest

from p40_flowbase.agents.mixin import AgentTasksDBMixin
from p40_flowbase.agents.models import (
    AgentTask,
    AgentTaskGroup,
)
from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.database import DBDataObject


class TestVersion(Enum):
    V1 = DataObjectVersion(
        id="test",
        name="Test",
        description="Test version",
    )


class TestAgentDB(AgentTasksDBMixin, DBDataObject):
    """Minimal DB object for testing agent retry logic."""

    id = "test_agent"
    description = "Test Agent DB"
    supported_versions = (TestVersion.V1,)
    schema = [AgentTaskGroup, AgentTask]


@pytest.fixture
async def agent_db(test_data_local_tmp):
    db = TestAgentDB(TestVersion.V1)
    await db.make_async(replace=True)
    yield db
    await db.close()

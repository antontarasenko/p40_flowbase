import unittest.mock
import uuid
from datetime import (
    UTC,
    datetime,
)

import pytest
from sqlmodel import select

from p40_flowbase.agents.models import AgentTask
from p40_flowbase.agents.providers import AgentModels


class TestAgentRetry:
    @pytest.mark.asyncio
    async def test_retry_creates_new_tasks_and_sets_superseded_by_id(
        self,
        agent_db,
    ):
        failed_task = AgentTask(
            model=AgentModels.GPT_5_NANO,
            task_prompt="test task",
            started_at_utc=datetime.now(UTC),
            is_error=True,
            error_message="something failed",
        )
        async with agent_db.session_factory() as session:
            session.add(failed_task)
            await session.commit()
            await session.refresh(failed_task)

        original_id = failed_task.agent_task_id

        with unittest.mock.patch.object(
            type(agent_db),
            "_execute_pending_agent_tasks",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            await agent_db._retry_failed_agent_tasks()

        async with agent_db.session_factory() as session:
            result = await session.exec(
                select(AgentTask).where(
                    AgentTask.agent_task_id == original_id
                )
            )
            old_task = result.one()

        assert old_task.superseded_by_id is not None

        async with agent_db.session_factory() as session:
            result = await session.exec(
                select(AgentTask).where(
                    AgentTask.agent_task_id == old_task.superseded_by_id
                )
            )
            new_task = result.one()

        assert new_task.task_prompt == "test task"
        assert new_task.model == AgentModels.GPT_5_NANO

    @pytest.mark.asyncio
    async def test_retry_skips_already_superseded(self, agent_db):
        already_superseded = AgentTask(
            model=AgentModels.GPT_5_NANO,
            task_prompt="task a",
            started_at_utc=datetime.now(UTC),
            is_error=True,
            superseded_by_id=uuid.uuid4(),
        )
        not_superseded = AgentTask(
            model=AgentModels.GPT_5_NANO,
            task_prompt="task b",
            started_at_utc=datetime.now(UTC),
            is_error=True,
        )
        async with agent_db.session_factory() as session:
            session.add(already_superseded)
            session.add(not_superseded)
            await session.commit()
            await session.refresh(already_superseded)
            await session.refresh(not_superseded)

        with unittest.mock.patch.object(
            type(agent_db),
            "_execute_pending_agent_tasks",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            await agent_db._retry_failed_agent_tasks()

        async with agent_db.session_factory() as session:
            result = await session.exec(
                select(AgentTask).where(
                    AgentTask.agent_task_id == not_superseded.agent_task_id
                )
            )
            task = result.one()
        assert task.superseded_by_id is not None

        async with agent_db.session_factory() as session:
            result = await session.exec(
                select(AgentTask).where(
                    AgentTask.agent_task_id
                    == already_superseded.agent_task_id
                )
            )
            task = result.one()
        assert task.superseded_by_id == already_superseded.superseded_by_id

    @pytest.mark.asyncio
    async def test_second_retry_does_not_re_retry_originals(self, agent_db):
        failed_task = AgentTask(
            model=AgentModels.GPT_5_NANO,
            task_prompt="test task",
            started_at_utc=datetime.now(UTC),
            is_error=True,
        )
        async with agent_db.session_factory() as session:
            session.add(failed_task)
            await session.commit()
            await session.refresh(failed_task)

        original_id = failed_task.agent_task_id

        mock_execute = unittest.mock.AsyncMock(return_value=[])

        with unittest.mock.patch.object(
            type(agent_db),
            "_execute_pending_agent_tasks",
            new=mock_execute,
        ):
            await agent_db._retry_failed_agent_tasks()

            async with agent_db.session_factory() as session:
                result = await session.exec(
                    select(AgentTask).where(
                        AgentTask.agent_task_id == original_id
                    )
                )
                old_task = result.one()
            first_superseded_by = old_task.superseded_by_id
            assert first_superseded_by is not None

            await agent_db._retry_failed_agent_tasks()

        async with agent_db.session_factory() as session:
            result = await session.exec(
                select(AgentTask).where(
                    AgentTask.agent_task_id == original_id
                )
            )
            old_task = result.one()

        assert old_task.superseded_by_id == first_superseded_by

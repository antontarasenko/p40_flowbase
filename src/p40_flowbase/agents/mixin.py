"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
import hashlib
import json
import pathlib
import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    override,
)

from p40_flowbase.agents.models import (
    AgentFile,
    AgentMessage,
    AgentTask,
    AgentToolCall,
)
from p40_flowbase.agents.providers import (
    AgentProviders,
)
from p40_flowbase.core.requests_mixin import RequestsDBMixin
from p40_flowbase.logging import logger

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement


class AgentDB(RequestsDBMixin[AgentTask]):
    """DB for executing agent tasks via the OpenAI / Anthropic agent SDKs.

    Subclasses should set ``tables`` to include at least ``AgentTaskGroup``,
    ``AgentTaskExtra``, ``AgentFile``, ``AgentTask``, ``AgentToolCall``, and
    ``AgentMessage``, and implement
    ``_populate_agent_tasks() -> uuid.UUID``.

    Configure API keys via ``AgentDB.set_api_keys(...)`` before execution.
    """

    rate_limit: ClassVar[float] = 1.0
    rate_period: ClassVar[float] = 1.0

    _request_model: ClassVar[type[Any] | None] = AgentTask
    _pending_column: ClassVar[str | None] = "started_at_utc"

    @classmethod
    @override
    def _failed_predicate(cls) -> "ColumnElement[bool] | None":
        from sqlalchemy import and_

        return and_(
            AgentTask.started_at_utc.is_not(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            AgentTask.is_error.is_(True),  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            AgentTask.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        )

    _openai_api_key: ClassVar[str | None] = None
    _anthropic_api_key: ClassVar[str | None] = None

    @classmethod
    def set_api_keys(
        cls,
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
    ) -> None:
        """Set API keys for agent providers."""
        cls._openai_api_key = openai_api_key
        cls._anthropic_api_key = anthropic_api_key

    @override
    async def _populate(self) -> uuid.UUID:
        if not hasattr(self, "_populate_agent_tasks"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement "
                "_populate_agent_tasks() method"
            )
        result: uuid.UUID = await self._populate_agent_tasks()  # pyright: ignore[reportAttributeAccessIssue]
        return result

    @override
    async def _execute_pending(
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
    ) -> list[AgentTask]:
        group_uuid = (
            uuid.UUID(group_id) if isinstance(group_id, str) else group_id
        )
        return await self._execute_pending_agent_tasks(
            rate_limit=rate_limit,
            rate_period=rate_period,
            agent_task_group_id=group_uuid,
        )

    @override
    async def _retry_failed(
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
    ) -> list[AgentTask]:
        group_uuid = (
            uuid.UUID(group_id) if isinstance(group_id, str) else group_id
        )
        return await self._retry_failed_agent_tasks(
            rate_limit=rate_limit,
            rate_period=rate_period,
            agent_task_group_id=group_uuid,
        )

    @override
    async def _get_wave_results(
        self,
        group_id: uuid.UUID,
    ) -> list[AgentTask]:
        return await self._get_agent_wave_results(group_id=group_id)

    async def _add_agent_tasks(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[AgentTask]:
        """Insert agent task rows for later execution."""
        created_tasks = []

        async with self.session_factory() as session:
            for task_data in tasks:
                allowed_tools = task_data.get("allowed_tools")
                allowed_tools_json = None
                if allowed_tools:
                    allowed_tools_json = json.dumps(allowed_tools)

                attachments = task_data.get("attachments")
                attachments_json = None
                if attachments:
                    normalized_attachments: list[str] = []
                    for file_id in attachments:
                        if isinstance(file_id, uuid.UUID):
                            normalized_attachments.append(file_id.hex)
                        else:
                            normalized_attachments.append(
                                str(file_id).replace("-", "").lower()
                            )
                    attachments_json = json.dumps(normalized_attachments)

                mcp_server_config = task_data.get("mcp_server_config")
                mcp_server_config_json = None
                if mcp_server_config:
                    mcp_server_config_json = json.dumps(mcp_server_config)

                output_format = task_data.get("output_format")
                output_format_json = None
                if output_format:
                    import pydantic as pyd

                    if isinstance(output_format, type) and issubclass(
                        output_format, pyd.BaseModel
                    ):
                        output_format_json = json.dumps({
                            "type": "json_schema",
                            "schema": output_format.model_json_schema(),
                        })
                    elif isinstance(output_format, dict):
                        output_format_json = json.dumps(output_format)
                    else:
                        output_format_json = json.dumps(output_format)

                agent_task = AgentTask(
                    model=task_data["model"],
                    task_prompt=task_data["task_prompt"],
                    system_prompt=task_data.get("system_prompt"),
                    effort=task_data.get("effort"),
                    allowed_tools=allowed_tools_json,
                    max_turns=task_data.get("max_turns"),
                    working_directory=task_data.get("working_directory"),
                    output_format=output_format_json,
                    attachments=attachments_json,
                    enable_custom_tools=task_data.get("enable_custom_tools", False),
                    mcp_server_config=mcp_server_config_json,
                    agent_task_group_id=task_data.get("agent_task_group_id"),
                    agent_task_extra_id=task_data.get("agent_task_extra_id"),
                )
                session.add(agent_task)
                created_tasks.append(agent_task)

            await session.commit()

            for agent_task in created_tasks:
                await session.refresh(agent_task)

        return created_tasks

    async def _add_agent_file(
        self,
        file_path: pathlib.Path,
        data_object_class_name: str,
        data_object_id: str,
        data_object_version: str,
        data_object_format: str,
    ) -> AgentFile:
        """Insert a file row into the agent_files table."""
        file_data = await asyncio.to_thread(file_path.read_bytes)
        md5sum = hashlib.md5(file_data, usedforsecurity=False).hexdigest()

        object_stem = f"{data_object_id}-{data_object_version}"
        local_dir = pathlib.Path(self.local_data) / object_stem
        format_path = local_dir / f"{object_stem}.{data_object_format}"

        if file_path == format_path:
            relative_path = "."
        else:
            relative_path = str(file_path.relative_to(local_dir))

        agent_file = AgentFile(
            name=file_path.name,
            md5sum=md5sum,
            size_bytes=len(file_data),
            data_object_class_name=data_object_class_name,
            data_object_id=data_object_id,
            data_object_version=data_object_version,
            data_object_format=data_object_format,
            local_tmp_path=relative_path,
        )

        async with self.session_factory() as session:
            session.add(agent_file)
            await session.commit()
            await session.refresh(agent_file)

        return agent_file

    async def _store_tool_calls(
        self,
        agent_task_id: uuid.UUID,
        tool_calls: list[dict[str, Any]],
    ) -> list[AgentToolCall]:
        """Store tool call records for a task."""
        created_tool_calls = []

        async with self.session_factory() as session:
            for tc_data in tool_calls:
                tool_call = AgentToolCall(
                    agent_task_id=agent_task_id,
                    turn_number=tc_data["turn_number"],
                    tool_name=tc_data["tool_name"],
                    tool_input=tc_data["tool_input"],
                    tool_output=tc_data.get("tool_output"),
                    is_error=tc_data.get("is_error", False),
                )
                session.add(tool_call)
                created_tool_calls.append(tool_call)

            await session.commit()

            for tool_call in created_tool_calls:
                await session.refresh(tool_call)

        return created_tool_calls

    async def _store_messages(
        self,
        agent_task_id: uuid.UUID,
        messages: list[dict[str, Any]],
    ) -> list[AgentMessage]:
        """Store conversation messages for a task."""
        created_messages = []

        async with self.session_factory() as session:
            for msg_data in messages:
                message = AgentMessage(
                    agent_task_id=agent_task_id,
                    turn_number=msg_data["turn_number"],
                    role=msg_data["role"],
                    content=msg_data["content"],
                )
                session.add(message)
                created_messages.append(message)

            await session.commit()

            for message in created_messages:
                await session.refresh(message)

        return created_messages

    @staticmethod
    def _validate_structured_output(
        task: AgentTask, final_response: str | None
    ) -> tuple[bool, str | None]:
        """Return (is_error, error_message) for a completed task's response.

        When ``task.output_format`` is set, the response must be valid JSON.
        Plain-text responses (e.g. provider rate-limit banners returned as
        ``message.result``) bypass exception handling and would otherwise be
        recorded as successful; this check surfaces them so ``retry()`` runs.
        """
        if not task.output_format:
            return False, None
        if not final_response:
            return True, "No response produced for task requiring structured output"
        try:
            json.loads(final_response)
        except (json.JSONDecodeError, ValueError) as ve:
            return True, f"Response is not valid JSON for required structured output: {ve}"
        return False, None

    async def _execute_single_agent_task(
        self,
        task: AgentTask,
    ) -> AgentTask:
        """Dispatch an agent task to the correct provider SDK."""
        provider = task.model.value.provider

        if provider == AgentProviders.OPENAI:
            return await self._execute_openai_agent(task)
        if provider == AgentProviders.ANTHROPIC:
            return await self._execute_anthropic_agent(task)
        raise ValueError(f"Unknown provider: {provider}")

    async def _execute_openai_agent(
        self,
        task: AgentTask,
    ) -> AgentTask:
        """Execute an agent task using the OpenAI Agents SDK."""
        import agents as openai_agents

        start_time = datetime.now(UTC)

        async with self.session_factory() as session:
            task.started_at_utc = start_time
            session.add(task)
            await session.commit()

        try:
            model_settings: Any = None
            if task.effort is not None:
                from openai.types.shared import Reasoning

                model_settings = openai_agents.ModelSettings(
                    reasoning=Reasoning(effort=task.effort),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                )

            agent = openai_agents.Agent(
                name="TaskAgent",
                instructions=task.system_prompt or "",
                model=task.model.value.api_id,
                model_settings=model_settings,
            )

            result = await openai_agents.Runner.run(
                starting_agent=agent,
                input=task.task_prompt,
            )

            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            tool_calls = []
            messages = []
            turn_number = 0

            for raw_item in result.new_items:
                item: Any = raw_item
                if hasattr(item, "raw_item"):
                    raw: Any = item.raw_item
                    if hasattr(raw, "role"):
                        messages.append({
                            "turn_number": turn_number,
                            "role": raw.role if hasattr(raw, "role") else "assistant",
                            "content": json.dumps(raw.model_dump()) if hasattr(raw, "model_dump") else str(raw),
                        })

                if hasattr(item, "type") and item.type == "tool_call_item":
                    tool_calls.append({
                        "turn_number": turn_number,
                        "tool_name": item.name if hasattr(item, "name") else "unknown",
                        "tool_input": json.dumps(item.call_args) if hasattr(item, "call_args") else "{}",
                        "tool_output": item.output if hasattr(item, "output") else None,
                        "is_error": False,
                    })

                turn_number += 1

            await self._store_tool_calls(task.agent_task_id, tool_calls)
            await self._store_messages(task.agent_task_id, messages)

            final_response = result.final_output
            is_error, error_message = self._validate_structured_output(task, final_response)

            async with self.session_factory() as session:
                task.final_response = final_response
                task.completed_at_utc = end_time
                task.duration_ms = duration_ms
                task.num_turns = len(result.new_items)
                task.is_error = is_error
                task.error_message = error_message
                session.add(task)
                await session.commit()
                await session.refresh(task)

        except Exception as e:  # noqa: BLE001  # capture any agent failure into the task row
            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            async with self.session_factory() as session:
                task.completed_at_utc = end_time
                task.duration_ms = duration_ms
                task.is_error = True
                task.error_message = str(e)
                session.add(task)
                await session.commit()
                await session.refresh(task)

            logger.error(f"OpenAI agent task failed: {e}")

        return task

    async def _execute_anthropic_agent(
        self,
        task: AgentTask,
    ) -> AgentTask:
        """Execute an agent task using the Anthropic Claude Agent SDK."""
        import claude_agent_sdk as claude_sdk

        start_time = datetime.now(UTC)

        async with self.session_factory() as session:
            task.started_at_utc = start_time
            session.add(task)
            await session.commit()

        try:
            allowed_tools = None
            if task.allowed_tools:
                allowed_tools = json.loads(task.allowed_tools)

            output_format = None
            if task.output_format:
                output_format = json.loads(task.output_format)

            options = claude_sdk.ClaudeAgentOptions(
                model=task.model.value.api_id,
                system_prompt=task.system_prompt,
                allowed_tools=allowed_tools,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
                cwd=task.working_directory,
                max_turns=task.max_turns,
                permission_mode="acceptEdits",
                output_format=output_format,  # pyright: ignore[reportCallIssue]
                effort=task.effort,  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType]
            )

            tool_calls = []
            messages = []
            turn_number = 0
            final_response = None
            num_turns = 0
            total_cost_usd = None

            async with claude_sdk.ClaudeSDKClient(options=options) as client:
                await client.query(task.task_prompt)

                async for message in client.receive_response():
                    if hasattr(message, "content"):
                        for block in message.content:  # pyright: ignore[reportAttributeAccessIssue]
                            if hasattr(block, "name") and hasattr(block, "input"):
                                tool_calls.append({
                                    "turn_number": turn_number,
                                    "tool_name": block.name,  # pyright: ignore[reportAttributeAccessIssue]
                                    "tool_input": json.dumps(block.input),  # pyright: ignore[reportAttributeAccessIssue]
                                    "tool_output": None,
                                    "is_error": False,
                                })
                            elif hasattr(block, "text"):
                                messages.append({
                                    "turn_number": turn_number,
                                    "role": "assistant",
                                    "content": block.text,  # pyright: ignore[reportAttributeAccessIssue]
                                })

                    if hasattr(message, "role"):
                        turn_number += 1

                    if hasattr(message, "structured_output") and message.structured_output:  # pyright: ignore[reportAttributeAccessIssue]
                        final_response = json.dumps(message.structured_output)  # pyright: ignore[reportAttributeAccessIssue]
                    elif hasattr(message, "result") and message.result:  # pyright: ignore[reportAttributeAccessIssue]
                        final_response = message.result  # pyright: ignore[reportAttributeAccessIssue]
                    if hasattr(message, "num_turns"):
                        num_turns = message.num_turns  # pyright: ignore[reportAttributeAccessIssue]
                    if hasattr(message, "total_cost_usd"):
                        total_cost_usd = message.total_cost_usd  # pyright: ignore[reportAttributeAccessIssue]

            await self._store_tool_calls(task.agent_task_id, tool_calls)
            await self._store_messages(task.agent_task_id, messages)

            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            is_error, error_message = self._validate_structured_output(task, final_response)

            async with self.session_factory() as session:
                task.final_response = final_response
                task.completed_at_utc = end_time
                task.duration_ms = duration_ms
                task.num_turns = num_turns
                task.total_cost_usd = total_cost_usd
                task.is_error = is_error
                task.error_message = error_message
                session.add(task)
                await session.commit()
                await session.refresh(task)

        except Exception as e:  # noqa: BLE001  # capture any agent failure into the task row
            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            async with self.session_factory() as session:
                task.completed_at_utc = end_time
                task.duration_ms = duration_ms
                task.is_error = True
                task.error_message = str(e)
                session.add(task)
                await session.commit()
                await session.refresh(task)

            logger.error(f"Anthropic agent task failed: {e}")

        return task

    async def _execute_pending_agent_tasks(
        self,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
        agent_task_group_id: uuid.UUID | None = None,
    ) -> list[AgentTask]:
        """Execute all agent tasks where ``started_at_utc`` is null."""
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(AgentTask).where(
                AgentTask.started_at_utc.is_(None)  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            if agent_task_group_id is not None:
                statement = statement.where(
                    AgentTask.agent_task_group_id == agent_task_group_id
                )
            result = await session.exec(statement)
            agent_tasks = result.all()

        return await self._run_batch(
            rows=list(agent_tasks),
            execute_one=self._execute_single_agent_task,
            rate_limit=rate_limit,
            rate_period=rate_period,
            is_success=lambda r: not r.is_error,
            progress_every=10,
            label="agent task",
        )

    async def _retry_failed_agent_tasks(
        self,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
        agent_task_group_id: uuid.UUID | None = None,
    ) -> list[AgentTask]:
        """Retry agent tasks that failed.

        Creates fresh ``AgentTask`` rows for each failed task (marking the
        originals as superseded) and executes them in a second pass.
        """
        import sqlalchemy
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(AgentTask).where(
                AgentTask.started_at_utc.is_not(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
                AgentTask.is_error.is_(True),  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
                AgentTask.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            if agent_task_group_id is not None:
                statement = statement.where(
                    AgentTask.agent_task_group_id == agent_task_group_id
                )
            result = await session.exec(statement)
            failed_tasks = result.all()

        retry_tasks_data = []
        for failed_task in failed_tasks:
            retry_data = {
                "model": failed_task.model,
                "task_prompt": failed_task.task_prompt,
                "system_prompt": failed_task.system_prompt,
                "allowed_tools": (
                    json.loads(failed_task.allowed_tools)
                    if failed_task.allowed_tools
                    else None
                ),
                "max_turns": failed_task.max_turns,
                "working_directory": failed_task.working_directory,
                "attachments": (
                    json.loads(failed_task.attachments)
                    if failed_task.attachments
                    else None
                ),
                "enable_custom_tools": failed_task.enable_custom_tools,
                "mcp_server_config": (
                    json.loads(failed_task.mcp_server_config)
                    if failed_task.mcp_server_config
                    else None
                ),
                "output_format": (
                    json.loads(failed_task.output_format)
                    if failed_task.output_format
                    else None
                ),
                "agent_task_group_id": failed_task.agent_task_group_id,
                "agent_task_extra_id": failed_task.agent_task_extra_id,
            }
            retry_tasks_data.append(retry_data)

        new_tasks = await self._add_agent_tasks(retry_tasks_data)

        async with self.session_factory() as session:
            for failed_task, new_task in zip(failed_tasks, new_tasks, strict=True):
                await session.exec(
                    sqlalchemy.update(AgentTask)
                    .where(
                        AgentTask.agent_task_id  # type: ignore[arg-type]
                        == failed_task.agent_task_id  # pyright: ignore[reportArgumentType]
                    )
                    .values(superseded_by_id=new_task.agent_task_id)
                )
            await session.commit()

        return await self._execute_pending_agent_tasks(
            rate_limit=rate_limit,
            rate_period=rate_period,
            agent_task_group_id=agent_task_group_id,
        )

    async def _get_agent_wave_results(
        self,
        group_id: uuid.UUID,
    ) -> list[AgentTask]:
        """Return non-superseded agent tasks for ``group_id``."""
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(AgentTask).where(
                AgentTask.agent_task_group_id == group_id,
                AgentTask.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            result = await session.exec(statement)
            return list(result.all())

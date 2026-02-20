"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
import hashlib
import json
import pathlib
import time
import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)

from p40_flowbase.agents.models import (
    AgentFile,
    AgentMessage,
    AgentTask,
    AgentToolCall,
)
from p40_flowbase.agents.providers import (
    AgentModels,
    AgentProviders,
)
from p40_flowbase.logging import logger


class AgentTasksDBMixin:
    """Mixin for executing agent tasks via LLM SDKs.

    Classes using this mixin must include AgentTaskGroup, AgentTaskExtra,
    AgentFile, AgentTask, AgentToolCall, and AgentMessage in their schema
    attribute.

    Subclasses should implement:
        - async def _populate_agent_tasks(self) -> uuid.UUID:
            Create and add agent tasks, return the group_id.

    Configuration:
        Set API keys via the set_api_keys classmethod before execution.
    """

    default_rate_limit: float = 1.0
    default_rate_period: float = 1.0

    # API keys - should be set by project config
    _openai_api_key: Optional[str] = None
    _anthropic_api_key: Optional[str] = None

    @classmethod
    def set_api_keys(
        cls,
        openai_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
    ) -> None:
        """Set API keys for agent providers.

        Args:
            openai_api_key: OpenAI API key.
            anthropic_api_key: Anthropic API key.
        """
        cls._openai_api_key = openai_api_key
        cls._anthropic_api_key = anthropic_api_key

    async def populate(self) -> uuid.UUID:
        """Populate agent tasks based on object version and configuration.

        Returns:
            UUID of the created task group.
        """
        if not hasattr(self, "_populate_agent_tasks"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement _populate_agent_tasks() method"
            )
        return await self._populate_agent_tasks()

    async def execute(
        self,
        group_id: Optional[uuid.UUID] = None,
        rate_limit: Optional[float] = None,
        rate_period: Optional[float] = None,
    ) -> List[AgentTask]:
        """Execute pending agent tasks.

        Args:
            group_id: If provided, only execute tasks from this group.
            rate_limit: Maximum tasks per rate_period. Defaults to self.default_rate_limit.
            rate_period: Time period in seconds for rate limiting. Defaults to self.default_rate_period.

        Returns:
            List of executed AgentTask entries.
        """
        return await self._execute_pending_agent_tasks(
            rate_limit=rate_limit if rate_limit is not None else self.default_rate_limit,
            rate_period=rate_period if rate_period is not None else self.default_rate_period,
            agent_task_group_id=group_id,
        )

    async def retry(
        self,
        group_id: Optional[uuid.UUID] = None,
        rate_limit: Optional[float] = None,
        rate_period: Optional[float] = None,
    ) -> List[AgentTask]:
        """Retry failed agent tasks.

        Args:
            group_id: If provided, only retry tasks from this group.
            rate_limit: Maximum tasks per rate_period. Defaults to self.default_rate_limit.
            rate_period: Time period in seconds for rate limiting. Defaults to self.default_rate_period.

        Returns:
            List of retried AgentTask entries.
        """
        return await self._retry_failed_agent_tasks(
            rate_limit=rate_limit if rate_limit is not None else self.default_rate_limit,
            rate_period=rate_period if rate_period is not None else self.default_rate_period,
            agent_task_group_id=group_id,
        )

    async def _add_agent_tasks(
        self,
        tasks: List[Dict[str, Any]],
    ) -> List[AgentTask]:
        """Add agent tasks to the database for later execution.

        Args:
            tasks: List of dicts with task fields. Each dict should contain:
                - model (AgentModels): Agent model enum
                - task_prompt (str): The task to perform
                - system_prompt (Optional[str]): System prompt
                - allowed_tools (Optional[List[str]]): List of tool names
                - max_turns (Optional[int]): Maximum conversation turns
                - working_directory (Optional[str]): Working directory for tools
                - attachments (Optional[List[str]]): List of agent_file_ids
                - enable_custom_tools (bool): Enable MCP custom tools
                - mcp_server_config (Optional[dict]): MCP server configuration
                - output_format (Optional[dict|Type[pydantic.BaseModel]]): Structured output format
                - agent_task_group_id (Optional[uuid.UUID]): Reference to group
                - agent_task_extra_id (Optional[uuid.UUID]): Reference to extra

        Returns:
            List of created AgentTask entries.
        """
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
                    normalized_attachments: List[str] = []
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
        """Add a file to the agent_files table.

        Args:
            file_path: Path to the file.
            data_object_class_name: Name of the data object class.
            data_object_id: ID of the data object.
            data_object_version: Version of the data object.
            data_object_format: Format of the data object.

        Returns:
            Created AgentFile entry.
        """
        with open(file_path, "rb") as f:
            file_data = f.read()
            md5sum = hashlib.md5(file_data).hexdigest()

        object_stem = f"{data_object_id}-{data_object_version}"
        local_dir = pathlib.Path(self.data_local_tmp) / object_stem
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
        tool_calls: List[Dict[str, Any]],
    ) -> List[AgentToolCall]:
        """Store tool call records in database.

        Args:
            agent_task_id: ID of the parent agent task.
            tool_calls: List of tool call dicts with:
                - turn_number (int)
                - tool_name (str)
                - tool_input (str): JSON string
                - tool_output (Optional[str]): JSON or text
                - is_error (bool)

        Returns:
            List of created AgentToolCall entries.
        """
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
        messages: List[Dict[str, Any]],
    ) -> List[AgentMessage]:
        """Store conversation messages in database.

        Args:
            agent_task_id: ID of the parent agent task.
            messages: List of message dicts with:
                - turn_number (int)
                - role (str): "assistant", "user", "system"
                - content (str): JSON string or plain text

        Returns:
            List of created AgentMessage entries.
        """
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

    async def _execute_single_agent_task(
        self,
        task: AgentTask,
    ) -> AgentTask:
        """Execute a single agent task using the appropriate SDK.

        Args:
            task: AgentTask to execute.

        Returns:
            Updated AgentTask with results.
        """
        provider = task.model.value.provider

        if provider == AgentProviders.OPENAI:
            return await self._execute_openai_agent(task)
        elif provider == AgentProviders.ANTHROPIC:
            return await self._execute_anthropic_agent(task)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def _execute_openai_agent(
        self,
        task: AgentTask,
    ) -> AgentTask:
        """Execute agent task using OpenAI Agents SDK.

        Args:
            task: AgentTask to execute.

        Returns:
            Updated AgentTask with results.
        """
        import agents as openai_agents

        start_time = datetime.now(UTC)

        async with self.session_factory() as session:
            task.started_at_utc = start_time
            session.add(task)
            await session.commit()

        try:
            agent = openai_agents.Agent(
                name="TaskAgent",
                instructions=task.system_prompt or "",
                model=task.model.value.api_id,
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

            for item in result.new_items:
                if hasattr(item, "raw_item"):
                    raw = item.raw_item
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

            async with self.session_factory() as session:
                task.final_response = result.final_output
                task.completed_at_utc = end_time
                task.duration_ms = duration_ms
                task.num_turns = len(result.new_items)
                task.is_error = False
                session.add(task)
                await session.commit()
                await session.refresh(task)

        except Exception as e:
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
        """Execute agent task using Anthropic Claude Agent SDK.

        Args:
            task: AgentTask to execute.

        Returns:
            Updated AgentTask with results.
        """
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
                allowed_tools=allowed_tools,
                cwd=task.working_directory,
                max_turns=task.max_turns,
                permission_mode="acceptEdits",
                output_format=output_format,
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
                        for block in message.content:
                            if hasattr(block, "name") and hasattr(block, "input"):
                                tool_calls.append({
                                    "turn_number": turn_number,
                                    "tool_name": block.name,
                                    "tool_input": json.dumps(block.input),
                                    "tool_output": None,
                                    "is_error": False,
                                })
                            elif hasattr(block, "text"):
                                messages.append({
                                    "turn_number": turn_number,
                                    "role": "assistant",
                                    "content": block.text,
                                })

                    if hasattr(message, "role"):
                        turn_number += 1

                    if hasattr(message, "structured_output") and message.structured_output:
                        final_response = json.dumps(message.structured_output)
                    elif hasattr(message, "result") and message.result:
                        final_response = message.result
                    if hasattr(message, "num_turns"):
                        num_turns = message.num_turns
                    if hasattr(message, "total_cost_usd"):
                        total_cost_usd = message.total_cost_usd

            await self._store_tool_calls(task.agent_task_id, tool_calls)
            await self._store_messages(task.agent_task_id, messages)

            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            async with self.session_factory() as session:
                task.final_response = final_response
                task.completed_at_utc = end_time
                task.duration_ms = duration_ms
                task.num_turns = num_turns
                task.total_cost_usd = total_cost_usd
                task.is_error = False
                session.add(task)
                await session.commit()
                await session.refresh(task)

        except Exception as e:
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
        agent_task_group_id: Optional[uuid.UUID] = None,
    ) -> List[AgentTask]:
        """Execute all agent tasks where started_at_utc is null.

        Args:
            rate_limit: Maximum number of tasks per rate_period.
            rate_period: Time period in seconds for rate limiting.
            agent_task_group_id: If provided, only process tasks from this group.

        Returns:
            List of executed AgentTask entries with results populated.
        """
        from aiolimiter import AsyncLimiter
        from sqlmodel import select

        limiter = AsyncLimiter(max_rate=rate_limit, time_period=rate_period)

        async with self.session_factory() as session:
            statement = select(AgentTask).where(AgentTask.started_at_utc.is_(None))
            if agent_task_group_id is not None:
                statement = statement.where(
                    AgentTask.agent_task_group_id == agent_task_group_id
                )
            result = await session.exec(statement)
            agent_tasks = result.all()

        async def rate_limited_task(task):
            async with limiter:
                pass
            return await self._execute_single_agent_task(task)

        tasks = [rate_limited_task(t) for t in agent_tasks]

        executed = []
        successful_count = 0
        failed_count = 0
        total_count = 0
        start_time = time.time()

        for completed_task in asyncio.as_completed(tasks):
            total_count += 1
            try:
                result = await completed_task
            except Exception as e:
                failed_count += 1
                logger.error(f"Agent task failed with exception: {e}")
                continue
            executed.append(result)

            if not result.is_error:
                successful_count += 1
            else:
                failed_count += 1

            if total_count % 10 == 0:
                elapsed = time.time() - start_time
                effective_rps = total_count / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {total_count} completed "
                    f"({successful_count} succeeded, {failed_count} failed), "
                    f"{elapsed:.1f}s elapsed, {effective_rps:.2f} tasks/s"
                )

        elapsed = time.time() - start_time
        effective_rps = total_count / elapsed if elapsed > 0 else 0
        logger.info(
            f"Completed processing {total_count} agent tasks: "
            f"{successful_count} succeeded, {failed_count} failed, "
            f"{elapsed:.1f}s total, {effective_rps:.2f} tasks/s"
        )

        return executed

    async def _retry_failed_agent_tasks(
        self,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
        agent_task_group_id: Optional[uuid.UUID] = None,
    ) -> List[AgentTask]:
        """Retry agent tasks that failed.

        Creates new AgentTask entries for each failed task and executes them.

        Args:
            rate_limit: Maximum number of tasks per rate_period.
            rate_period: Time period in seconds for rate limiting.
            agent_task_group_id: If provided, only process tasks from this group.

        Returns:
            List of new AgentTask entries created for retries.
        """
        import sqlalchemy
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(AgentTask).where(
                AgentTask.started_at_utc.is_not(None),
                AgentTask.is_error == True,
                AgentTask.superseded_by_id.is_(None),
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
            for failed_task, new_task in zip(failed_tasks, new_tasks):
                await session.execute(
                    sqlalchemy.update(AgentTask)
                    .where(
                        AgentTask.agent_task_id == failed_task.agent_task_id
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
    ) -> List[AgentTask]:
        """Get non-superseded agent tasks for a group.

        Args:
            group_id: The task group UUID.

        Returns:
            List of AgentTask entries that have not been superseded.
        """
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(AgentTask).where(
                AgentTask.agent_task_group_id == group_id,
                AgentTask.superseded_by_id.is_(None),
            )
            result = await session.exec(statement)
            return result.all()

    async def _execute_agent_task_graph(
        self,
        lanes: List[str],
        num_steps: int,
        populate_step: Callable,
        rate_limit: Optional[float] = None,
        rate_period: Optional[float] = None,
        max_retries: int = 1,
        checkpointer: Optional[Any] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, List[list]]:
        """Execute a parallel-lane, sequential-step graph for agent tasks.

        Args:
            lanes: List of lane identifiers.
            num_steps: Number of sequential steps per lane.
            populate_step: Async callback ``(lane_id, step_index, prev_results) -> Optional[UUID]``.
            rate_limit: Maximum tasks per rate_period.
            rate_period: Time period in seconds for rate limiting.
            max_retries: Maximum retry attempts per step.
            checkpointer: Optional LangGraph checkpointer.
            thread_id: Thread ID for checkpointer resumability.

        Returns:
            Dict mapping lane_id to list of step results (each a list of AgentTask).
        """
        from p40_flowbase.orchestration.graphs import (
            build_recursive_task_graph,
        )

        effective_rate_limit = rate_limit if rate_limit is not None else self.default_rate_limit
        effective_rate_period = rate_period if rate_period is not None else self.default_rate_period

        async def execute_pending_wrapper(group_id_str: str) -> list:
            group_uuid = (
                uuid.UUID(group_id_str)
                if isinstance(group_id_str, str)
                else group_id_str
            )
            return await self._execute_pending_agent_tasks(
                rate_limit=effective_rate_limit,
                rate_period=effective_rate_period,
                agent_task_group_id=group_uuid,
            )

        async def retry_failed_wrapper(group_id_str: str) -> list:
            group_uuid = (
                uuid.UUID(group_id_str)
                if isinstance(group_id_str, str)
                else group_id_str
            )
            return await self._retry_failed_agent_tasks(
                rate_limit=effective_rate_limit,
                rate_period=effective_rate_period,
                agent_task_group_id=group_uuid,
            )

        async def get_wave_results_wrapper(group_id: uuid.UUID) -> list:
            return await self._get_agent_wave_results(group_id=group_id)

        graph = build_recursive_task_graph(
            populate_step=populate_step,
            execute_pending=execute_pending_wrapper,
            retry_failed=retry_failed_wrapper,
            get_wave_results=get_wave_results_wrapper,
            checkpointer=checkpointer,
        )

        config = {}
        if thread_id is not None or checkpointer is not None:
            config["configurable"] = {
                "thread_id": thread_id or uuid.uuid4().hex,
            }

        result = await graph.ainvoke(
            {
                "lanes": lanes,
                "num_steps": num_steps,
                "max_retries": max_retries,
                "lane_results": [],
            },
            config=config if config else None,
        )

        return result.get("organized_results", {})

    async def execute_graph(
        self,
        lanes: List[str],
        num_steps: int,
        populate_step: Optional[Callable] = None,
        rate_limit: Optional[float] = None,
        rate_period: Optional[float] = None,
        max_retries: int = 1,
        checkpointer: Optional[Any] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, List[list]]:
        """Execute a parallel-lane, sequential-step graph for agent tasks.

        Convenience method that defaults populate_step to self._populate_lane_step.

        Args:
            lanes: List of lane identifiers.
            num_steps: Number of sequential steps per lane.
            populate_step: Async callback ``(lane_id, step_index, prev_results) -> Optional[UUID]``.
                Defaults to self._populate_lane_step if not provided.
            rate_limit: Maximum tasks per rate_period.
            rate_period: Time period in seconds for rate limiting.
            max_retries: Maximum retry attempts per step.
            checkpointer: Optional LangGraph checkpointer.
            thread_id: Thread ID for checkpointer resumability.

        Returns:
            Dict mapping lane_id to list of step results (each a list of AgentTask).
        """
        if populate_step is None:
            if not hasattr(self, "_populate_lane_step"):
                raise NotImplementedError(
                    f"{self.__class__.__name__} must implement _populate_lane_step() "
                    "or pass populate_step argument"
                )
            populate_step = self._populate_lane_step

        return await self._execute_agent_task_graph(
            lanes=lanes,
            num_steps=num_steps,
            populate_step=populate_step,
            rate_limit=rate_limit,
            rate_period=rate_period,
            max_retries=max_retries,
            checkpointer=checkpointer,
            thread_id=thread_id,
        )

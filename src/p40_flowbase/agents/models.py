"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import uuid
from datetime import (
    UTC,
    datetime,
)

from sqlalchemy import (
    Column,
)
from sqlalchemy import (
    Enum as SQLAEnum,
)
from sqlmodel import (
    Field,
    SQLModel,
)

from p40_flowbase.agents.providers import (
    AgentEffort,
    AgentModels,
)


class AgentTaskGroup(SQLModel, table=True):
    """Group of related agent tasks.

    Subclass this to add custom fields for your use case.
    """

    __tablename__ = "agent_task_groups"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_task_group_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class AgentTaskExtra(SQLModel, table=True):
    """Extra metadata for agent tasks.

    Subclass this to add custom fields for your use case.
    """

    __tablename__ = "agent_task_extra"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_task_extra_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class AgentFile(SQLModel, table=True):
    """File attachment for agent tasks.

    Tracks files that are passed as input to agent tasks.
    """

    __tablename__ = "agent_files"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_file_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    name: str
    md5sum: str
    size_bytes: int
    data_object_class_name: str
    data_object_id: str
    data_object_version: str
    data_object_format: str
    local_tmp_path: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentTask(SQLModel, table=True):
    """Agent task record.

    Represents a single task to be executed by an LLM agent.
    """

    __tablename__ = "agent_tasks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_task_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Configuration
    model: AgentModels = Field(sa_column=Column(SQLAEnum(AgentModels)))
    effort: AgentEffort | None = Field(
        default=None,
        sa_column=Column(SQLAEnum(AgentEffort), nullable=True),
    )
    system_prompt: str | None = None
    task_prompt: str
    allowed_tools: str | None = None
    max_turns: int | None = None
    working_directory: str | None = None
    output_format: str | None = None

    # Attachments
    attachments: str | None = None

    # Custom tools
    enable_custom_tools: bool = False
    mcp_server_config: str | None = None

    # Grouping
    agent_task_group_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="agent_task_groups.agent_task_group_id",
    )
    agent_task_extra_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="agent_task_extra.agent_task_extra_id",
    )

    # Execution tracking
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None

    # Output
    final_response: str | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    total_cost_usd: float | None = None
    is_error: bool = False
    error_message: str | None = None
    superseded_by_id: uuid.UUID | None = None


class AgentToolCall(SQLModel, table=True):
    """Individual tool invocation within an agent task.

    Tracks each tool call made by the agent during execution.
    """

    __tablename__ = "agent_tool_calls"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_tool_call_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    agent_task_id: uuid.UUID = Field(foreign_key="agent_tasks.agent_task_id")

    turn_number: int
    tool_name: str
    tool_input: str
    tool_output: str | None = None
    is_error: bool = False

    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentMessage(SQLModel, table=True):
    """Conversation message within an agent task.

    Stores the full conversation history including reasoning.
    """

    __tablename__ = "agent_messages"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_message_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    agent_task_id: uuid.UUID = Field(foreign_key="agent_tasks.agent_task_id")

    turn_number: int
    role: str
    content: str

    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))

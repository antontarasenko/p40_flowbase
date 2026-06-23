"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import Any, override

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

from p40_flowbase.providers import (
    AGENT_SUPPORTED_PROVIDERS,
    ModelVersion,
    Providers,
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

    Represents a single task to be executed by an LLM agent. The model spec is
    stored as flattened scalar columns; construct with
    ``AgentTask.from_spec(Models.X, ...)`` or assemble the columns directly.
    Provider must be in ``AGENT_SUPPORTED_PROVIDERS``.
    """

    __tablename__ = "agent_tasks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    agent_task_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Configuration
    model_id: str
    model_api_id: str
    model_name: str
    model_provider: Providers = Field(
        sa_column=Column(SQLAEnum(Providers), nullable=False),
    )
    model_input_token_price_usd: float | None = None
    model_output_token_price_usd: float | None = None

    effort: str | None = None
    system_prompt: str | None = None
    task_prompt: str
    allowed_tools: str | None = None
    max_turns: int | None = None
    working_directory: str | None = None
    output_format: str | None = None

    expected_input_cost_usd: float | None = None

    attachments: str | None = None

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

    @classmethod
    def from_spec(cls, spec: ModelVersion, **kwargs: Any) -> "AgentTask":
        """Construct an ``AgentTask`` from a ``ModelVersion`` spec.

        :raises ValueError: If ``spec.provider`` is not supported by
            an agent SDK.
        """
        if spec.provider not in AGENT_SUPPORTED_PROVIDERS:
            msg = (
                f"AgentTask does not support provider {spec.provider!r}; "
                f"supported: {sorted(p.value for p in AGENT_SUPPORTED_PROVIDERS)}"
            )
            raise ValueError(msg)
        return cls(
            model_id=spec.id,
            model_api_id=spec.api_id,
            model_name=spec.name,
            model_provider=spec.provider,
            model_input_token_price_usd=spec.input_token_price_usd,
            model_output_token_price_usd=spec.output_token_price_usd,
            **kwargs,
        )

    @property
    def model(self) -> ModelVersion:
        """Reconstruct the ``ModelVersion`` spec from the persisted columns."""
        return ModelVersion(
            id=self.model_id,
            api_id=self.model_api_id,
            name=self.model_name,
            provider=self.model_provider,
            input_token_price_usd=self.model_input_token_price_usd,
            output_token_price_usd=self.model_output_token_price_usd,
        )

    @override
    def model_post_init(self, __context: Any) -> None:  # noqa: PYI063
        """Calculate ``expected_input_cost_usd`` from prompts when price is known."""
        if self.model_input_token_price_usd is None:
            return
        system_prompt = self.system_prompt or ""
        task_prompt = self.task_prompt or ""
        total_chars = len(system_prompt) + len(task_prompt)
        self.expected_input_cost_usd = (
            (total_chars / 4) * 1.1 * self.model_input_token_price_usd
        )


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

"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import uuid
from typing import Any, override
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

from p40_flowbase.llm.providers import (
    LLMEffort,
    LLMModels,
)


class LLMRequestGroup(SQLModel, table=True):
    """Group of related LLM requests.

    Subclasses can extend this table with additional columns to parametrize groups.
    """

    __tablename__ = "llm_request_groups"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    llm_request_group_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class LLMRequestExtra(SQLModel, table=True):
    """Extra metadata for LLM requests.

    Subclasses can extend this table with additional columns.
    """

    __tablename__ = "llm_requests_extra"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    llm_request_extra_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class LLMFile(SQLModel, table=True):
    """File attachment for LLM requests."""

    __tablename__ = "llm_files"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    llm_file_id: uuid.UUID = Field(
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
    local_tmp_path: str  # Path relative to data object format path

    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LLMRequest(SQLModel, table=True):
    """LLM request and its response."""

    __tablename__ = "llm_requests"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    llm_request_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model: LLMModels = Field(sa_column=Column(SQLAEnum(LLMModels)))
    temperature: float | None = None
    effort: LLMEffort | None = Field(
        default=None,
        sa_column=Column(SQLAEnum(LLMEffort), nullable=True),
    )
    system_prompt: str | None = None
    user_prompt: str | None = None
    attachments: str | None = None  # JSON list of llm_file_ids
    response_schema: str | None = None  # JSON schema for structured output
    expected_input_cost_usd: float | None = None

    http_request_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="http_requests.http_request_id",
    )

    response_text: str | None = None
    response_attachments: str | None = None  # JSON list of llm_file_ids

    llm_request_group_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="llm_request_groups.llm_request_group_id",
    )
    llm_request_extra_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="llm_requests_extra.llm_request_extra_id",
    )

    requested_at_utc: datetime | None = None
    superseded_by_id: uuid.UUID | None = None

    @override
    def model_post_init(self, __context: Any) -> None:  # noqa: PYI063
        """Calculate expected_input_cost_usd from prompts."""
        system_prompt = self.system_prompt or ""
        user_prompt = self.user_prompt or ""
        total_chars = len(system_prompt) + len(user_prompt)
        self.expected_input_cost_usd = (
            (total_chars / 4) * 1.1 * self.model.value.input_token_price_usd
        )

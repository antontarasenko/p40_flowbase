"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import uuid
from datetime import (
    UTC,
    datetime,
)

from sqlmodel import (
    Field,
    SQLModel,
)


class HTTPRequestGroup(SQLModel, table=True):
    """Group of related HTTP requests.

    Subclasses can extend this table with additional columns to parametrize groups.
    """

    __tablename__ = "http_request_groups"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    http_request_group_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class HTTPRequestExtra(SQLModel, table=True):
    """Extra metadata for HTTP requests.

    Subclasses can extend this table with additional columns.
    """

    __tablename__ = "http_requests_extra"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    http_request_extra_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class HTTPRequest(SQLModel, table=True):
    """HTTP request and its response."""

    __tablename__ = "http_requests"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    http_request_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    http_request_group_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="http_request_groups.http_request_group_id",
    )
    http_request_extra_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="http_requests_extra.http_request_extra_id",
    )

    request_url: str
    request_method: str
    request_headers: str | None = None
    request_body: str | None = None

    response_status: int | None = None
    response_headers: str | None = None
    response_body_text: str | None = None
    response_size: int | None = None

    latency: float | None = None

    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requested_at_utc: datetime | None = None
    superseded_by_id: uuid.UUID | None = None

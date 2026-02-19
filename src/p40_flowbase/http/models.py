"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import Optional

from sqlmodel import (
    Field,
    SQLModel,
)


class HTTPRequestGroup(SQLModel, table=True):
    """Group of related HTTP requests.

    Subclasses can extend this table with additional columns to parametrize groups.
    """

    __tablename__ = "http_request_groups"
    __table_args__ = {"extend_existing": True}

    http_request_group_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class HTTPRequestExtra(SQLModel, table=True):
    """Extra metadata for HTTP requests.

    Subclasses can extend this table with additional columns.
    """

    __tablename__ = "http_requests_extra"
    __table_args__ = {"extend_existing": True}

    http_request_extra_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )


class HTTPRequest(SQLModel, table=True):
    """HTTP request and its response."""

    __tablename__ = "http_requests"
    __table_args__ = {"extend_existing": True}

    http_request_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    http_request_group_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="http_request_groups.http_request_group_id",
    )
    http_request_extra_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="http_requests_extra.http_request_extra_id",
    )

    request_url: str
    request_method: str
    request_headers: Optional[str] = None
    request_body: Optional[str] = None

    response_status: Optional[int] = None
    response_headers: Optional[str] = None
    response_body_text: Optional[str] = None
    response_size: Optional[int] = None

    latency: Optional[float] = None

    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requested_at_utc: Optional[datetime] = None
    superseded_by_id: Optional[uuid.UUID] = None

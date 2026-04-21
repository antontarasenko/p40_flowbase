"""
MIT License

Copyright (c) 2025 Anton Tarasenko

Factories for downstream-specific ``{Prefix}RequestGroup`` / ``{Prefix}RequestExtra``
tables. Each factory produces a SQLModel ``table=True`` class with the standard
primary key + ``created_at_utc`` + ``created_by_class`` columns, plus any extra
columns passed as keyword arguments.
"""

import types
import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Any,
)

from sqlmodel import (
    Field,
    SQLModel,
)


def _snake_to_camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _coerce_field(spec: Any) -> tuple[Any, Any]:
    """Return ``(annotation, default)`` from a column spec.

    Accepted forms:
        * ``type`` -> required column (``...`` default)
        * ``(type, default)`` -> column with explicit default
        * ``(type, sqlmodel.Field(...))`` -> column with full ``Field``
    """
    if isinstance(spec, tuple):
        if len(spec) != 2:
            raise ValueError(
                f"Column spec tuple must be (type, default), got {spec!r}"
            )
        return spec
    return spec, ...


def _build_table(
    class_name: str,
    table_name: str,
    base_fields: dict[str, tuple[Any, Any]],
    extra_cols: dict[str, Any],
) -> type[SQLModel]:
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for name, (ann, default) in base_fields.items():
        annotations[name] = ann
        if default is not ...:
            defaults[name] = default
    for name, spec in extra_cols.items():
        ann, default = _coerce_field(spec)
        annotations[name] = ann
        if default is not ...:
            defaults[name] = default

    def body(ns: dict[str, Any]) -> None:
        ns["__tablename__"] = table_name
        ns["__table_args__"] = {"extend_existing": True}
        ns["__annotations__"] = annotations
        for name, default in defaults.items():
            ns[name] = default

    return types.new_class(
        class_name,
        (SQLModel,),
        {"table": True},
        body,
    )


def _primary_key_field() -> Any:
    return Field(default_factory=uuid.uuid4, primary_key=True)


def _created_at_field() -> Any:
    return Field(default_factory=lambda: datetime.now(UTC))


def make_http_request_group_table(
    prefix: str,
    **extra_cols: Any,
) -> type[SQLModel]:
    """Create an ``{prefix}_http_request_groups`` SQLModel table.

    Standard columns: ``http_request_group_id``, ``created_at_utc``,
    ``created_by_class``. Additional columns from ``extra_cols``.
    """
    return _build_table(
        class_name=f"{_snake_to_camel(prefix)}HTTPRequestGroup",
        table_name=f"{prefix}_http_request_groups",
        base_fields={
            "http_request_group_id": (uuid.UUID, _primary_key_field()),
            "created_at_utc": (datetime, _created_at_field()),
            "created_by_class": (str, ...),
        },
        extra_cols=extra_cols,
    )


def make_http_request_extra_table(
    prefix: str,
    **extra_cols: Any,
) -> type[SQLModel]:
    """Create an ``{prefix}_http_request_extra`` SQLModel table."""
    return _build_table(
        class_name=f"{_snake_to_camel(prefix)}HTTPRequestExtra",
        table_name=f"{prefix}_http_request_extra",
        base_fields={
            "http_request_extra_id": (uuid.UUID, _primary_key_field()),
        },
        extra_cols=extra_cols,
    )


def make_llm_request_group_table(
    prefix: str,
    **extra_cols: Any,
) -> type[SQLModel]:
    """Create an ``{prefix}_llm_request_groups`` SQLModel table."""
    return _build_table(
        class_name=f"{_snake_to_camel(prefix)}LLMRequestGroup",
        table_name=f"{prefix}_llm_request_groups",
        base_fields={
            "llm_request_group_id": (uuid.UUID, _primary_key_field()),
            "created_at_utc": (datetime, _created_at_field()),
            "created_by_class": (str, ...),
        },
        extra_cols=extra_cols,
    )


def make_llm_request_extra_table(
    prefix: str,
    **extra_cols: Any,
) -> type[SQLModel]:
    """Create an ``{prefix}_llm_request_extra`` SQLModel table."""
    return _build_table(
        class_name=f"{_snake_to_camel(prefix)}LLMRequestExtra",
        table_name=f"{prefix}_llm_request_extra",
        base_fields={
            "llm_request_extra_id": (uuid.UUID, _primary_key_field()),
        },
        extra_cols=extra_cols,
    )


def make_agent_task_group_table(
    prefix: str,
    **extra_cols: Any,
) -> type[SQLModel]:
    """Create an ``{prefix}_agent_task_groups`` SQLModel table."""
    return _build_table(
        class_name=f"{_snake_to_camel(prefix)}AgentTaskGroup",
        table_name=f"{prefix}_agent_task_groups",
        base_fields={
            "agent_task_group_id": (uuid.UUID, _primary_key_field()),
            "created_at_utc": (datetime, _created_at_field()),
            "created_by_class": (str, ...),
        },
        extra_cols=extra_cols,
    )


def make_agent_task_extra_table(
    prefix: str,
    **extra_cols: Any,
) -> type[SQLModel]:
    """Create an ``{prefix}_agent_task_extra`` SQLModel table."""
    return _build_table(
        class_name=f"{_snake_to_camel(prefix)}AgentTaskExtra",
        table_name=f"{prefix}_agent_task_extra",
        base_fields={
            "agent_task_extra_id": (uuid.UUID, _primary_key_field()),
        },
        extra_cols=extra_cols,
    )

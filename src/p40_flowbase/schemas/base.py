"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import datetime as dt
from typing import Any

import pydantic as pyd
import sqlmodel as sm


class SchemaBase(sm.SQLModel):
    """Universal base for catalog schemas: strict fields, naive-UTC datetimes.

    A non-table ``SQLModel`` subclass, so one schema class serves every
    backend: per-line ``model_validate_json`` for NDJSON seeds and
    Composite files, ``arrow_schema_from_pydantic`` for ``Table``
    row schemas, ``class Row(Schema, table=True)`` for DB tables, and
    ``model_json_schema()`` (``additionalProperties: false`` under
    ``extra="forbid"``) as an LLM structured-output contract.

    Subclasses must stay inside the flat-scalar subset: ``int``,
    ``float``, ``bool``, ``str``, ``bytes``, ``datetime``, ``date``,
    ``Decimal`` and ``Optional`` of those; vocabularies are
    pattern-constrained ``str`` (``Literal``/``StrEnum`` do not map to
    Arrow); no nested models, lists, or unions.

    Caveat: ``table=True`` subclasses skip validation on ``__init__``
    (upstream SQLModel behavior); construct DB rows from an already
    validated non-table instance or via ``model_validate``.
    """

    model_config = pyd.ConfigDict(extra="forbid")  # type: ignore[assignment]  # pyright: ignore[reportAssignmentType]

    @pyd.field_validator("*", mode="after")
    @classmethod
    def _naive_utc(cls, value: Any) -> Any:
        # A tz-aware datetime (e.g. a "...Z" seed timestamp) would store
        # as UTC in parquet but wall-clock in SQLite; normalize once,
        # here, for every datetime field including subclass-added ones.
        if isinstance(value, dt.datetime) and value.tzinfo is not None:
            return value.astimezone(dt.UTC).replace(tzinfo=None)
        return value

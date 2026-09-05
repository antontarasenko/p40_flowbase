"""Storage-decoupled record schemas, mainly quality contracts for LLM agents.

One schema class serves five backends: git-versioned NDJSON/TSV seed
resources (per-line ``model_validate_json``), ``Table.row_schema``
(Arrow-validated parquet), DB tables (``class Row(Schema, table=True)``
plus a primary key), ``ck.SchemaMatches`` on Composite JSON files, and
LLM structured-output contracts (``model_json_schema()`` /
``client.messages.parse``).

Recommended import, mirroring ``from p40_flowbase import checks as ck``::

    from p40_flowbase import schemas as sc

    class QuarterlyRevenue(sc.PeriodObservation):
        revenue_gaap_b_usd: float

Projects keep domain schemas in their own ``schemas/`` package (beside
``objects/``); promotion into this catalog requires at least two
concrete use cases, flat-scalar subset fit, and a domain-neutral
vocabulary.
"""

from p40_flowbase.schemas.base import SchemaBase
from p40_flowbase.schemas.observation import (
    ENTITY_ID_SYSTEM_PATTERN,
    REF_ID_PATTERN,
    InstantObservation,
    MetricObservation,
    Observation,
    PeriodObservation,
    ReferenceBase,
    normalize_text,
    verify_quote,
)

__all__ = [
    "ENTITY_ID_SYSTEM_PATTERN",
    "REF_ID_PATTERN",
    "InstantObservation",
    "MetricObservation",
    "Observation",
    "PeriodObservation",
    "ReferenceBase",
    "SchemaBase",
    "normalize_text",
    "verify_quote",
]

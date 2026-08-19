"""``AnthropicCityNarrativeTable``: agent narratives flattened to a table."""

from enum import Enum
from typing import (
    ClassVar,
    override,
)

import p40_flowbase as fb
import pyarrow as pa
import pydantic as pyd
import sqlmodel as sm
from p40_flowbase import checks as ck

from p40_weather.objects.anthropic_city_narrative_agent_db import (
    AnthropicAgentTaskExtra,
    AnthropicCityNarrativeAgentDB,
)
from p40_weather.objects.versions import SUPPORTED_VERSIONS


class NarrativeRow(pyd.BaseModel):
    """One LLM-written narrative for one city.

    Field metadata follows the project's convention: ``title`` /
    ``description`` / ``examples`` are JSON-Schema-standard,
    ``json_schema_extra={"units": ...}`` carries machine-readable
    units for downstream tooling.
    """

    city: str = pyd.Field(
        title="City name",
        description="Human-readable city name (matches the version's TSV).",
        examples=["Los Angeles", "Tokyo"],
    )
    narrative: str = pyd.Field(
        title="Narrative sentence",
        description="One-sentence weather narrative produced by the agent.",
        examples=[
            "Los Angeles saw mild conditions with temperatures from "
            "12 to 25 °C and negligible precipitation.",
        ],
    )
    model_id: str = pyd.Field(
        title="Model id",
        description="Stable id of the ``fb.ModelVersion`` that wrote the narrative.",
        examples=["claude_sonnet_4_6"],
    )
    cost_usd: float = pyd.Field(
        title="Actual cost",
        description="Actual USD cost reported by the agent SDK.",
        examples=[0.0001, 0.0023],
        json_schema_extra={"units": "usd"},
    )


@fb.asset(deps=fb.AUTO)
class AnthropicCityNarrativeTable(fb.TableFromDB[AnthropicCityNarrativeAgentDB]):
    """Flatten the agent DB into a ``(city, narrative, model_id, cost_usd)`` table."""

    id: ClassVar[str] = "anthropic_city_narrative_table"
    description: ClassVar[str] = "Per-city LLM narrative + cost."
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    db_class: ClassVar[type] = AnthropicCityNarrativeAgentDB
    row_schema: ClassVar[type[pyd.BaseModel]] = NarrativeRow
    # The narrative join filters to is_error=False; if every task fails
    # this would be a 0-row parquet that passes the schema gate.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRows(1),
        ck.NoNulls("city", "narrative"),
    )

    @override
    async def _build_df(self, db: AnthropicCityNarrativeAgentDB) -> pa.Table:
        async with db.session_factory() as session:
            rows = (
                await session.exec(
                    sm.select(fb.AgentTask, AnthropicAgentTaskExtra)
                    .join(
                        AnthropicAgentTaskExtra,
                        fb.AgentTask.agent_task_extra_id  # type: ignore[arg-type]
                        == AnthropicAgentTaskExtra.agent_task_extra_id,  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
                    )
                    .where(fb.AgentTask.is_error.is_(False))  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
                )
            ).all()
        return pa.Table.from_pylist([
            {
                "city": extra.city,  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
                "narrative": (task.final_response or "").strip(),
                "model_id": task.model_id,
                "cost_usd": float(task.total_cost_usd or 0.0),
            }
            for task, extra in rows
        ])

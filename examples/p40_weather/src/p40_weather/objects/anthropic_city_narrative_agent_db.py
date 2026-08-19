"""``AnthropicCityNarrativeAgentDB``: per-city LLM narratives, plus its audit tables."""

import uuid
from enum import Enum
from typing import (
    Any,
    ClassVar,
)

import p40_flowbase as fb
from p40_flowbase import checks as ck

from p40_weather.objects.open_meteo_city_summary_table import OpenMeteoCitySummaryTable
from p40_weather.objects.versions import (
    SUPPORTED_VERSIONS,
    narrow_version,
)

#: Per-run audit row for the agent step. Captures which version + which
#: model produced the narratives so the DB has a self-contained record.
AnthropicAgentTaskGroup = fb.make_agent_task_group_table(
    "anthropic",
    version_id=str,
    model_id=str,
    cities_count=int,
)

#: Per-task metadata. One row per ``fb.AgentTask``, FK-linked via
#: ``fb.AgentTask.agent_task_extra_id``. Carries the city name so the
#: downstream ``AnthropicCityNarrativeTable`` can join without parsing
#: the prompt text.
AnthropicAgentTaskExtra = fb.make_agent_task_extra_table(
    "anthropic",
    city=str,
)


def _narrative_prompt(row: dict[str, Any]) -> str:
    """Render the agent prompt template for one summary row."""
    return fb.render_jinja_template(
        template_name="anthropic_city_narrative_agent_db.md.jinja",
        package="p40_weather",
        subpath="resources/templates/prompts",
        city=row["city"],
        temp_min_c=row["temp_min_c"],
        temp_mean_c=row["temp_mean_c"],
        temp_max_c=row["temp_max_c"],
        precip_total_mm=row["precip_total_mm"],
    )


@fb.asset(deps=fb.AUTO)
class AnthropicCityNarrativeAgentDB(fb.AgentDB):
    """One ``fb.AgentTask`` per city; writes a one-sentence weather narrative.

    Default model is ``fb.Models.CLAUDE_SONNET_4_6``. Override
    ``model_spec`` on a subclass (or set the class attribute on this
    class itself) to swap providers; cost is reported on the per-object
    log via the framework's ``fb.AgentDB._summary_queries`` aggregate.
    """

    id: ClassVar[str] = "anthropic_city_narrative_agent_db"
    description: ClassVar[str] = (
        "One agent task per city; one-sentence weather narrative."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    tables: ClassVar[list[Any]] = [
        AnthropicAgentTaskGroup,
        AnthropicAgentTaskExtra,
        fb.AgentTask,
        fb.AgentToolCall,
        fb.AgentMessage,
    ]
    # No silent skip if the agent fails on every city.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRequests(1),
        ck.MaxFailureRate(frac=0.0),
    )

    #: Default model. Override to swap providers / cost.
    model_spec: ClassVar[fb.ModelVersion] = fb.Models.CLAUDE_SONNET_4_6

    # Anthropic per-workspace request limits for Sonnet 4.6 (per Anthropic
    # docs, 2026): Tier 1 = 50 RPM, Tier 2 = 1_000 RPM, Tier 3 = 2_000 RPM,
    # Tier 4 = 4_000 RPM. We pick 0.5 req/s (= 30 RPM) as the safe default
    # for Tier-1 accounts with headroom for parallel work in the same
    # workspace. Override via ``make(rate_limit=..., rate_period=...)`` if
    # you have a higher tier. The Sonnet single-turn round-trip is 5-10 s
    # in practice, so this rate limit only matters when the API gets fast
    # enough that we'd otherwise burst above the per-minute cap.
    rate_limit: ClassVar[float] = 0.5
    rate_period: ClassVar[float] = 1.0

    async def _populate_agent_tasks(self) -> uuid.UUID:
        wv = narrow_version(self.version)
        # Pattern: order in SQL so the agent tasks are built deterministically.
        summary_rows: list[dict[str, Any]] = (
            OpenMeteoCitySummaryTable(self.version)
            .sql("SELECT * FROM t ORDER BY city")
            .to_arrow_table()
            .to_pylist()
        )
        group_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                AnthropicAgentTaskGroup(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                    agent_task_group_id=group_id,
                    created_by_class=type(self).__name__,
                    version_id=wv.id,
                    model_id=self.model_spec.id,
                    cities_count=len(summary_rows),
                )
            )
            for row in summary_rows:
                extra_id = uuid.uuid4()
                session.add(
                    AnthropicAgentTaskExtra(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                        agent_task_extra_id=extra_id,
                        city=row["city"],
                    )
                )
                session.add(
                    fb.AgentTask.from_spec(
                        self.model_spec,
                        task_prompt=_narrative_prompt(row),
                        agent_task_group_id=group_id,
                        agent_task_extra_id=extra_id,
                    )
                )
            await session.commit()
        return group_id

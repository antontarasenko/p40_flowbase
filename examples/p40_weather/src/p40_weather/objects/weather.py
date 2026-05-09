"""DataObject subclasses forming the p40_weather pipeline.

Pipeline::

    WeatherHTTPDB → WeatherResponseFiles → WeatherHourlyTable
        → WeatherSummaryTable → WeatherCityNarrativeAgentDB
            → WeatherCityNarrativeTable
                → WeatherFigure / WeatherDoc
"""

import csv
import datetime as _dt
import importlib.resources
import io
import json
import pickle
import uuid
import warnings
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import matplotlib.pyplot as plt
import pyarrow as pa
import pydantic as pyd
import sqlmodel as sm

import p40_flowbase as fb
from p40_weather.helpers import build_forecast_url

################################################################################
# Version metadata
################################################################################


@dataclass(frozen=True)
class WeatherVersion(fb.DataObjectVersion):
    """Per-version pipeline parameters.

    :ivar cities: ``(name, latitude, longitude)`` tuples to fetch.
    :vartype cities: tuple[tuple[str, float, float], ...]
    :ivar forecast_days: Number of forecast days requested per city
        (Open-Meteo accepts 1..16).
    :vartype forecast_days: int
    """

    cities: tuple[tuple[str, float, float], ...] = field(default=())
    forecast_days: int = 1


def _load_cities(version_id: str) -> tuple[tuple[str, float, float], ...]:
    """Load ``(name, lat, lon)`` tuples from a versioned TSV resource.

    Reads ``p40_weather/resources/versions/weather_versions/cities-<version_id>.tsv``
    via ``importlib.resources``. The TSV must have a header row
    ``name<TAB>latitude<TAB>longitude``.

    :param version_id: ``WeatherVersion.id`` (matches the TSV stem after
        the ``cities-`` prefix).
    :type version_id: str
    :returns: Immutable tuple of ``(name, latitude, longitude)`` rows.
    :rtype: tuple[tuple[str, float, float], ...]
    """
    text = (
        importlib.resources.files("p40_weather")
        .joinpath(
            "resources",
            "versions",
            "weather_versions",
            f"cities-{version_id}.tsv",
        )
        .read_text(encoding="utf-8")
    )
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    next(reader)  # header
    return tuple(
        (row[0], float(row[1]), float(row[2])) for row in reader if row
    )


class WeatherVersions(Enum):
    """Supported versions for the p40_weather pipeline."""

    MAIN = WeatherVersion(
        id="main",
        name="main",
        description="5 cities, single-day hourly forecast.",
        cities=_load_cities("main"),
        forecast_days=1,
    )
    BACKFILL_2025 = WeatherVersion(
        id="backfill_2025",
        name="2025 backfill",
        description="Same 5 cities, max-horizon (16-day) forecast.",
        cities=_load_cities("backfill_2025"),
        forecast_days=16,
    )


_SUPPORTED: tuple[Enum, ...] = (
    WeatherVersions.MAIN,
    WeatherVersions.BACKFILL_2025,
)


def _wv(version: Enum) -> WeatherVersion:
    """Narrow ``self.version`` (typed as ``Enum``) to ``WeatherVersion``."""
    value = version.value
    if not isinstance(value, WeatherVersion):
        msg = f"Expected WeatherVersion, got {type(value).__name__}"
        raise TypeError(msg)
    return value

################################################################################
# Pydantic row schemas
################################################################################


class HourlyRow(pyd.BaseModel):
    """One hour of weather for one city.

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
    ts_utc: _dt.datetime = pyd.Field(
        title="Observation timestamp",
        description="Hourly observation timestamp in UTC.",
        examples=[_dt.datetime(2026, 1, 1, 0, 0, tzinfo=_dt.UTC)],
    )
    temp_c: float = pyd.Field(
        title="Air temperature",
        description="Air temperature 2 m above ground at this hour.",
        examples=[5.0, 15.5, -3.2],
        json_schema_extra={"units": "degC"},
    )
    precip_mm: float = pyd.Field(
        title="Precipitation",
        description="Liquid-equivalent precipitation accumulated over the hour.",
        examples=[0.0, 0.4, 12.7],
        json_schema_extra={"units": "mm"},
    )


class SummaryRow(pyd.BaseModel):
    """Per-city aggregate over the hourly window.

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
    temp_min_c: float = pyd.Field(
        title="Minimum temperature",
        description="Lowest hourly air temperature observed in the window.",
        examples=[-5.1, 3.0],
        json_schema_extra={"units": "degC"},
    )
    temp_mean_c: float = pyd.Field(
        title="Mean temperature",
        description="Arithmetic mean of hourly air temperatures.",
        examples=[7.4, 22.1],
        json_schema_extra={"units": "degC"},
    )
    temp_max_c: float = pyd.Field(
        title="Maximum temperature",
        description="Highest hourly air temperature observed in the window.",
        examples=[12.8, 31.0],
        json_schema_extra={"units": "degC"},
    )
    precip_total_mm: float = pyd.Field(
        title="Total precipitation",
        description="Sum of liquid-equivalent precipitation over the window.",
        examples=[0.0, 4.2, 88.6],
        json_schema_extra={"units": "mm"},
    )


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


################################################################################
# HTTP requests DB
################################################################################


#: Per-run audit row. One row inserted by ``_populate_http_requests``;
#: captures the ``WeatherVersion`` parameters at populate time so later
#: queries against the DB don't need to re-look up the version metadata
#: (and so changes to ``WeatherVersions`` after a run can't rewrite history).
WeatherHTTPRequestGroup = fb.make_http_request_group_table(
    "weather",
    version_id=str,
    forecast_days=int,
    cities_count=int,
)

#: Per-request metadata. One row per ``fb.HTTPRequest``, joined via
#: ``fb.HTTPRequest.http_request_extra_id``. Lets downstream consumers
#: read the city name and coordinates straight off the join instead
#: of parsing the URL or re-resolving the version's city catalog.
WeatherHTTPRequestExtra = fb.make_http_request_extra_table(
    "weather",
    city_name=str,
    latitude=float,
    longitude=float,
)


class WeatherHTTPDB(fb.HTTPDB):
    """SQLite of HTTP requests against Open-Meteo, one row per city.

    Each ``make()`` call writes:

    * one ``WeatherHTTPRequestGroup`` row carrying the version's
      audit fields (``version_id``, ``forecast_days``, ``cities_count``).
    * one ``WeatherHTTPRequestExtra`` row per city with denormalized
      ``city_name`` / ``latitude`` / ``longitude``.
    * one ``fb.HTTPRequest`` row per city, FK-linked to both extras.
    """

    id: ClassVar[str] = "weather_http_db"
    description: ClassVar[str] = (
        "HTTP requests for hourly forecasts (cities + days from the version)."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    tables: ClassVar[list[Any]] = [
        WeatherHTTPRequestGroup,
        WeatherHTTPRequestExtra,
        fb.HTTPRequest,
    ]

    async def _populate_http_requests(self) -> uuid.UUID:
        wv = _wv(self.version)
        group_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                WeatherHTTPRequestGroup(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                    http_request_group_id=group_id,
                    created_by_class=type(self).__name__,
                    version_id=wv.id,
                    forecast_days=wv.forecast_days,
                    cities_count=len(wv.cities),
                )
            )
            for name, lat, lon in wv.cities:
                extra_id = uuid.uuid4()
                session.add(
                    WeatherHTTPRequestExtra(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                        http_request_extra_id=extra_id,
                        city_name=name,
                        latitude=lat,
                        longitude=lon,
                    )
                )
                session.add(
                    fb.HTTPRequest(
                        request_url=build_forecast_url(
                            latitude=lat,
                            longitude=lon,
                            forecast_days=wv.forecast_days,
                        ),
                        request_method="GET",
                        http_request_group_id=group_id,
                        http_request_extra_id=extra_id,
                    )
                )
            await session.commit()
        return group_id


################################################################################
# Composite: one JSON file per city
################################################################################


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_")


class WeatherResponseFiles(fb.Composite):
    """One ``<city>.json`` file per successful HTTP response.

    The city name comes straight from a join on
    ``WeatherHTTPRequestExtra`` — no URL parsing, no reverse lat/lon
    lookup. This is the payoff of the per-request Extra table.
    """

    id: ClassVar[str] = "weather_response_files"
    description: ClassVar[str] = "Per-city Open-Meteo JSON responses."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(fb.CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)

        async def _dump() -> None:
            db = WeatherHTTPDB(self.version)
            try:
                async with db.session_factory() as session:
                    rows = (
                        await session.exec(
                            sm.select(fb.HTTPRequest, WeatherHTTPRequestExtra)
                            .join(
                                WeatherHTTPRequestExtra,
                                fb.HTTPRequest.http_request_extra_id  # type: ignore[arg-type]
                                == WeatherHTTPRequestExtra.http_request_extra_id,  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
                            )
                            .where(fb.HTTPRequest.response_status == 200)
                        )
                    ).all()
                for req, extra in rows:
                    body = req.response_body_text or ""
                    city = extra.city_name  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
                    (files_dir / f"{_slugify(city)}.json").write_text(body)
            finally:
                await db.close()

        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_dump())
        else:
            msg = "WeatherResponseFiles._make cannot run inside an event loop."
            raise RuntimeError(msg)


################################################################################
# Table: hourly long-form parquet
################################################################################


class WeatherHourlyTable(fb.Table):
    """Hourly long-form table built from the per-city JSON files."""

    id: ClassVar[str] = "weather_hourly_table"
    description: ClassVar[str] = (
        "Hourly (city, ts_utc, temp_c, precip_mm) rows."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    row_schema: ClassVar[type[pyd.BaseModel]] = HourlyRow

    @override
    def _make(self) -> None:
        files_dir = WeatherResponseFiles(self.version).path_to_format(
            fb.CompositeFormat.FILES,
        )
        rows: list[dict[str, Any]] = []
        for json_path in sorted(files_dir.glob("*.json")):
            payload = json.loads(json_path.read_text())
            city = json_path.stem.replace("_", " ").title()
            hourly = payload.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            precs = hourly.get("precipitation", [])
            for t, temp, prec in zip(times, temps, precs, strict=False):
                rows.append(
                    {
                        "city": city,
                        "ts_utc": _dt.datetime.fromisoformat(t),
                        "temp_c": float(temp),
                        "precip_mm": float(prec),
                    }
                )
        arrow = pa.Table.from_pylist(rows)
        self.save_arrow(arrow)


################################################################################
# Summary Table via .sql.jinja
################################################################################


class WeatherSummaryTable(fb.Table):
    """Per-city aggregates rendered from a DuckDB+Jinja SQL template."""

    id: ClassVar[str] = "weather_summary_table"
    description: ClassVar[str] = (
        "Per-city min/mean/max temp + total precip."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    row_schema: ClassVar[type[pyd.BaseModel]] = SummaryRow
    template_package: ClassVar[str | None] = "p40_weather"

    @override
    def _make(self) -> None:
        hourly = WeatherHourlyTable(self.version)
        hourly_path = hourly.path_to_format(fb.TableFormat.PARQUET).resolve()
        self.make_via_sql_template(
            template_vars={"hourly_path": str(hourly_path)},
        )


################################################################################
# AgentDB: per-city LLM narratives
################################################################################


#: Per-run audit row for the agent step. Captures which version + which
#: model produced the narratives so the DB has a self-contained record.
WeatherAgentTaskGroup = fb.make_agent_task_group_table(
    "weather",
    version_id=str,
    model_id=str,
    cities_count=int,
)

#: Per-task metadata. One row per ``fb.AgentTask``, FK-linked via
#: ``fb.AgentTask.agent_task_extra_id``. Carries the city name so the
#: downstream ``WeatherCityNarrativeTable`` can join without parsing
#: the prompt text.
WeatherAgentTaskExtra = fb.make_agent_task_extra_table(
    "weather",
    city=str,
)


def _narrative_prompt(row: dict[str, Any]) -> str:
    """Render the agent prompt template for one summary row."""
    return fb.render_sql_template(
        template_name="weather_city_narrative_agent_db.md.jinja",
        package="p40_weather",
        subpath="resources/templates/prompts",
        city=row["city"],
        temp_min_c=row["temp_min_c"],
        temp_mean_c=row["temp_mean_c"],
        temp_max_c=row["temp_max_c"],
        precip_total_mm=row["precip_total_mm"],
    )


class WeatherCityNarrativeAgentDB(fb.AgentDB):
    """One ``fb.AgentTask`` per city; writes a one-sentence weather narrative.

    Default model is ``fb.Models.CLAUDE_SONNET_4_6``. Override
    ``model_spec`` on a subclass (or set the class attribute on this
    class itself) to swap providers; cost is reported on the per-object
    log via the framework's ``fb.AgentDB._summary_queries`` aggregate.
    """

    id: ClassVar[str] = "weather_city_narrative_agent_db"
    description: ClassVar[str] = (
        "One agent task per city; one-sentence weather narrative."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    tables: ClassVar[list[Any]] = [
        WeatherAgentTaskGroup,
        WeatherAgentTaskExtra,
        fb.AgentTask,
        fb.AgentToolCall,
        fb.AgentMessage,
    ]

    #: Default model. Override to swap providers / cost.
    model_spec: ClassVar[fb.ModelVersion] = fb.Models.CLAUDE_SONNET_4_6

    async def _populate_agent_tasks(self) -> uuid.UUID:
        wv = _wv(self.version)
        summary_rows: list[dict[str, Any]] = (
            WeatherSummaryTable(self.version).df.to_pylist()
        )
        group_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                WeatherAgentTaskGroup(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
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
                    WeatherAgentTaskExtra(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
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


################################################################################
# TableFromDB: narratives joined to cities
################################################################################


class WeatherCityNarrativeTable(fb.TableFromDB[WeatherCityNarrativeAgentDB]):
    """Flatten the agent DB into a ``(city, narrative, model_id, cost_usd)`` table."""

    id: ClassVar[str] = "weather_city_narrative_table"
    description: ClassVar[str] = "Per-city LLM narrative + cost."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    db_class: ClassVar[type] = WeatherCityNarrativeAgentDB
    row_schema: ClassVar[type[pyd.BaseModel]] = NarrativeRow

    @override
    async def _build_df(self, db: WeatherCityNarrativeAgentDB) -> pa.Table:
        async with db.session_factory() as session:
            rows = (
                await session.exec(
                    sm.select(fb.AgentTask, WeatherAgentTaskExtra)
                    .join(
                        WeatherAgentTaskExtra,
                        fb.AgentTask.agent_task_extra_id  # type: ignore[arg-type]
                        == WeatherAgentTaskExtra.agent_task_extra_id,  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
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


################################################################################
# Figure: bar chart of mean temperatures
################################################################################


class WeatherFigure(fb.Figure):
    """Bar chart of mean temperature by city."""

    id: ClassVar[str] = "weather_figure"
    description: ClassVar[str] = "Mean temperature bar chart."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED

    @override
    def _make(self) -> None:
        summary = WeatherSummaryTable(self.version).df
        cities: list[str] = summary["city"].to_pylist()  # type: ignore[assignment]
        means: list[float] = summary["temp_mean_c"].to_pylist()  # type: ignore[assignment]

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(cities, means)
        ax.set_ylabel("Mean temperature (°C)")
        ax.set_title("Mean temperature by city")
        fig.tight_layout()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        with open(self.path_to_format(fb.FigureFormat.PKL), "wb") as f:
            # matplotlib figures pickle internal itertools state — Python 3.14
            # deprecates that, but we don't use the affected APIs.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    category=DeprecationWarning,
                    message="Pickle, copy, and deepcopy",
                )
                pickle.dump(fig, f)
        plt.close(fig)


################################################################################
# Document: markdown with embedded SVG + table
################################################################################


def _markdown_table(arrow: pa.Table) -> str:
    """Render a small pyarrow table as a GitHub-flavored Markdown table."""
    cols = arrow.column_names
    rows = arrow.to_pylist()
    buf = io.StringIO()
    buf.write("| " + " | ".join(cols) + " |\n")
    buf.write("| " + " | ".join("---" for _ in cols) + " |\n")
    for r in rows:
        formatted = [
            f"{r[c]:.2f}" if isinstance(r[c], float) else str(r[c])
            for c in cols
        ]
        buf.write("| " + " | ".join(formatted) + " |\n")
    return buf.getvalue()


class WeatherDoc(fb.Document):
    """Markdown report: summary table + embedded SVG + agent narratives."""

    id: ClassVar[str] = "weather_doc"
    description: ClassVar[str] = "Per-city weather report."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    template_package: ClassVar[str | None] = "p40_weather"

    @override
    def _make_data(self) -> None:
        figure = WeatherFigure(self.version)
        svg_path = figure.path_to_format(fb.FigureFormat.SVG)
        if not svg_path.exists():
            figure.convert(fb.FigureFormat.SVG)
        svg_text = svg_path.read_text()

        summary_table = _markdown_table(WeatherSummaryTable(self.version).df)

        narrative_rows = (
            WeatherCityNarrativeTable(self.version).df.to_pylist()
        )
        narratives = [
            {"city": r["city"], "narrative": r["narrative"]}
            for r in narrative_rows
        ]

        self.data = {
            "summary_table": summary_table,
            "figure_svg": svg_text,
            "narratives": narratives,
            "run_date": _dt.datetime.now(_dt.UTC).date().isoformat(),
        }

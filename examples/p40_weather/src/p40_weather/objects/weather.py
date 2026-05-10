"""DataObject subclasses forming the p40_weather pipeline.
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
    asdict,
    dataclass,
)
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import matplotlib

matplotlib.use("Agg")  # headless: Dagster runs each asset in a non-GUI subprocess

import matplotlib.pyplot as plt  # must follow matplotlib.use(...)
import p40_flowbase as fb
import pyarrow as pa
import pydantic as pyd
import sqlmodel as sm
from p40_flowbase import checks as ck

from p40_weather.helpers import build_forecast_url

################################################################################
# Version metadata
################################################################################


@dataclass(frozen=True)
class WeatherVersion(fb.DataObjectVersion):
    """Per-version pipeline parameters.

    Holds only declarative knobs. The per-version city catalog lives
    in its own ``DataObject`` (``WeatherInputCities``) sourced from
    ``resources/versions/weather_versions/cities-<id>.tsv``, so this
    enum stays import-time pure and trivially serializable.

    :ivar forecast_days: Number of forecast days requested per city
        (Open-Meteo accepts 1..16).
    :vartype forecast_days: int
    """

    forecast_days: int = 1


class WeatherVersions(Enum):
    """Supported versions for the p40_weather pipeline."""

    MAIN = WeatherVersion(
        id="main",
        name="main",
        description="5 cities, single-day hourly forecast.",
        forecast_days=1,
    )
    BACKFILL_2025 = WeatherVersion(
        id="backfill_2025",
        name="2025 backfill",
        description="Same 5 cities, max-horizon (16-day) forecast.",
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
# Version key-value snapshot Table
################################################################################


class VersionConfigRow(pyd.BaseModel):
    """One key-value row of a ``WeatherVersion``'s fields."""

    key: str = pyd.Field(
        title="Field name",
        description="Name of a ``WeatherVersion`` dataclass field.",
        examples=["id", "forecast_days"],
    )
    value: str = pyd.Field(
        title="Field value",
        description=(
            "Stringified field value (every column is ``str`` so the "
            "schema stays uniform across heterogeneous field types)."
        ),
        examples=["main", "16"],
    )


@fb.asset()
class WeatherVersionConfig(fb.Table):
    """Snapshot of the active ``WeatherVersion``'s fields as key-value rows.

    Useful for downstream debugging and audit: persists what the version
    metadata looked like at run time, in the same parquet folder layout
    as the rest of the pipeline. Picks up new ``WeatherVersion`` fields
    automatically because it iterates ``dataclasses.asdict``.
    """

    id: ClassVar[str] = "weather_version_config"
    description: ClassVar[str] = "Active WeatherVersion fields, key-value rows."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    row_schema: ClassVar[type[pyd.BaseModel]] = VersionConfigRow

    @override
    def _make(self) -> None:
        wv = _wv(self.version)
        rows = [{"key": k, "value": str(v)} for k, v in asdict(wv).items()]
        self.save_arrow(pa.Table.from_pylist(rows))


################################################################################
# Input cities Table (loaded from a versioned TSV resource)
################################################################################


def _load_cities(version_id: str) -> list[dict[str, float | str]]:
    """Read ``cities-<version_id>.tsv`` from package resources."""
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
    return [
        {"name": row[0], "latitude": float(row[1]), "longitude": float(row[2])}
        for row in reader
        if row
    ]


class CityRow(pyd.BaseModel):
    """One city in the per-version input catalog."""

    name: str = pyd.Field(
        title="City name",
        description="Human-readable city name.",
        examples=["Los Angeles", "Tokyo"],
    )
    latitude: float = pyd.Field(
        title="Latitude",
        description="Decimal-degrees latitude (WGS84).",
        examples=[34.0522, -33.9249],
        json_schema_extra={"units": "deg"},
    )
    longitude: float = pyd.Field(
        title="Longitude",
        description="Decimal-degrees longitude (WGS84).",
        examples=[-118.2437, 18.4241],
        json_schema_extra={"units": "deg"},
    )


@fb.asset()
class WeatherInputCities(fb.Table):
    """Per-version city catalog, materialized from the TSV resource.

    Reads ``resources/versions/weather_versions/cities-<id>.tsv`` and
    writes a parquet validated against ``CityRow``. Lifting the catalog
    into its own ``DataObject`` keeps ``WeatherVersions`` import-time
    pure (no disk IO at class-body evaluation) and gives downstream
    stages a single source of truth they can ``.df``-read like any
    other parquet.
    """

    id: ClassVar[str] = "weather_input_cities"
    description: ClassVar[str] = "Per-version (name, latitude, longitude) catalog."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    row_schema: ClassVar[type[pyd.BaseModel]] = CityRow

    @override
    def _make(self) -> None:
        rows = _load_cities(self.version.value.id)
        self.save_arrow(pa.Table.from_pylist(rows))


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


@fb.asset(deps=fb.AUTO)
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
    # Catch zero-row populates and any 4xx/5xx response from Open-Meteo.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRequests(1),
        ck.MaxFailureRate(frac=0.0),
    )

    # Open-Meteo free-tier rate limits (per their docs, 2026): 10 req/s,
    # 600 req/min, 5_000 req/h, 10_000 req/day. We pick 3/s for headroom
    # under the per-second cap and to play nicely with concurrent runs in
    # the same workspace. Override via ``make(rate_limit=..., rate_period=...)``
    # if you have a paid plan with higher limits.
    rate_limit: ClassVar[float] = 3.0
    rate_period: ClassVar[float] = 1.0

    async def _populate_http_requests(self) -> uuid.UUID:
        wv = _wv(self.version)
        cities_df = WeatherInputCities(self.version).df
        cities_rows: list[dict[str, Any]] = cities_df.to_pylist()
        group_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                WeatherHTTPRequestGroup(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                    http_request_group_id=group_id,
                    created_by_class=type(self).__name__,
                    version_id=wv.id,
                    forecast_days=wv.forecast_days,
                    cities_count=len(cities_rows),
                )
            )
            for row in cities_rows:
                name = row["name"]
                lat = row["latitude"]
                lon = row["longitude"]
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


@fb.asset(deps=fb.AUTO)
class WeatherResponseFiles(fb.Composite):
    """One ``<city>.json`` file per successful HTTP response.

    The city name comes straight from a join on
    ``WeatherHTTPRequestExtra`` — no URL parsing, no reverse lat/lon
    lookup. This is the payoff of the per-request Extra table.
    """

    id: ClassVar[str] = "weather_response_files"
    description: ClassVar[str] = "Per-city Open-Meteo JSON responses."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    # Each successful HTTP response writes one file; truncated downloads
    # surface as 0-byte files.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinFiles(1),
        ck.NoEmptyFiles(),
    )

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


@fb.asset(deps=fb.AUTO)
class WeatherHourlyTable(fb.Table):
    """Hourly long-form table built from the per-city JSON files."""

    id: ClassVar[str] = "weather_hourly_table"
    description: ClassVar[str] = (
        "Hourly (city, ts_utc, temp_c, precip_mm) rows."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    row_schema: ClassVar[type[pyd.BaseModel]] = HourlyRow
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRows(1),
        ck.NoNulls("city", "ts_utc", "temp_c"),
    )

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


@fb.asset(deps=fb.AUTO, convert_formats=[fb.TableFormat.TSV])
class WeatherSummaryTable(fb.Table):
    """Per-city aggregates rendered from a DuckDB+Jinja SQL template."""

    id: ClassVar[str] = "weather_summary_table"
    description: ClassVar[str] = (
        "Per-city min/mean/max temp + total precip."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    row_schema: ClassVar[type[pyd.BaseModel]] = SummaryRow
    template_package: ClassVar[str | None] = "p40_weather"
    # One row per city; city is the natural key for downstream joins.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRows(1),
        ck.NoNulls("city", "temp_mean_c"),
        ck.Unique("city"),
    )

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
    return fb.render_jinja_template(
        template_name="weather_city_narrative_agent_db.md.jinja",
        package="p40_weather",
        subpath="resources/templates/prompts",
        city=row["city"],
        temp_min_c=row["temp_min_c"],
        temp_mean_c=row["temp_mean_c"],
        temp_max_c=row["temp_max_c"],
        precip_total_mm=row["precip_total_mm"],
    )


@fb.asset(deps=fb.AUTO)
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
class WeatherCityNarrativeTable(fb.TableFromDB[WeatherCityNarrativeAgentDB]):
    """Flatten the agent DB into a ``(city, narrative, model_id, cost_usd)`` table."""

    id: ClassVar[str] = "weather_city_narrative_table"
    description: ClassVar[str] = "Per-city LLM narrative + cost."
    supported_versions: ClassVar[tuple[Enum, ...]] = _SUPPORTED
    db_class: ClassVar[type] = WeatherCityNarrativeAgentDB
    row_schema: ClassVar[type[pyd.BaseModel]] = NarrativeRow
    # The narrative join filters to is_error=False; if every task fails
    # this would be a 0-row parquet that passes the schema gate.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRows(1),
        ck.NoNulls("city", "narrative"),
    )

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


@fb.asset(deps=fb.AUTO)
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


@fb.asset(deps=fb.AUTO, convert_formats=[fb.DocumentFormat.PDF])
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

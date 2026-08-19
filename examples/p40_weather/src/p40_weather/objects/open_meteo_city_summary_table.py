"""``OpenMeteoCitySummaryTable``: per-city aggregates via a DuckDB+Jinja SQL template."""

from enum import Enum
from typing import (
    ClassVar,
    override,
)

import p40_flowbase as fb
import pydantic as pyd
from p40_flowbase import checks as ck

from p40_weather.objects.open_meteo_city_hourly_table import OpenMeteoCityHourlyTable
from p40_weather.objects.versions import SUPPORTED_VERSIONS


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
class OpenMeteoCitySummaryTable(fb.Table):
    """Per-city aggregates rendered from a DuckDB+Jinja SQL template."""

    id: ClassVar[str] = "open_meteo_city_summary_table"
    description: ClassVar[str] = (
        "Per-city min/mean/max temp + total precip."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
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
        hourly = OpenMeteoCityHourlyTable(self.version)
        hourly_path = hourly.path_to_format(fb.TableFormat.PARQUET).resolve()
        self.make_via_sql_template(
            template_vars={"hourly_path": str(hourly_path)},
        )

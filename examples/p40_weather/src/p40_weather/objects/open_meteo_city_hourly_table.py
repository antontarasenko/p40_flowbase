"""``OpenMeteoCityHourlyTable``: hourly long-form parquet from the per-city JSONs."""

import datetime as _dt
import json
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import p40_flowbase as fb
import pyarrow as pa
import pydantic as pyd
from p40_flowbase import checks as ck

from p40_weather.objects.open_meteo_forecast_response_files import OpenMeteoForecastResponseFiles
from p40_weather.objects.versions import SUPPORTED_VERSIONS


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
class OpenMeteoCityHourlyTable(fb.Table):
    """Hourly long-form table built from the per-city JSON files."""

    id: ClassVar[str] = "open_meteo_city_hourly_table"
    description: ClassVar[str] = (
        "Hourly (city, ts_utc, temp_c, precip_mm) rows."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    row_schema: ClassVar[type[pyd.BaseModel]] = HourlyRow
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRows(1),
        ck.NoNulls("city", "ts_utc", "temp_c"),
    )

    @override
    def _make(self) -> None:
        files_dir = OpenMeteoForecastResponseFiles(self.version).path_to_format(
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

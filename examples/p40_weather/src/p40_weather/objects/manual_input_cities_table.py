"""``ManualInputCitiesTable``: per-version city catalog from a TSV resource."""

import csv
import importlib.resources
import io
from enum import Enum
from typing import (
    ClassVar,
    override,
)

import p40_flowbase as fb
import pyarrow as pa
import pydantic as pyd

from p40_weather.objects.versions import SUPPORTED_VERSIONS


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
        {"name": row[0], "latitude_deg": float(row[1]), "longitude_deg": float(row[2])}
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
    latitude_deg: float = pyd.Field(
        title="Latitude",
        description="Decimal-degrees latitude (WGS84).",
        examples=[34.0522, -33.9249],
        json_schema_extra={"units": "deg"},
    )
    longitude_deg: float = pyd.Field(
        title="Longitude",
        description="Decimal-degrees longitude (WGS84).",
        examples=[-118.2437, 18.4241],
        json_schema_extra={"units": "deg"},
    )


@fb.asset()
class ManualInputCitiesTable(fb.Table):
    """Per-version city catalog, materialized from the TSV resource.

    Reads ``resources/versions/weather_versions/cities-<id>.tsv`` and
    writes a parquet validated against ``CityRow``. Lifting the catalog
    into its own ``DataObject`` keeps ``WeatherVersions`` import-time
    pure (no disk IO at class-body evaluation) and gives downstream
    stages a single source of truth they can ``.sql``-query like any
    other parquet.
    """

    id: ClassVar[str] = "manual_input_cities_table"
    description: ClassVar[str] = "Per-version (name, latitude_deg, longitude_deg) catalog."
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    row_schema: ClassVar[type[pyd.BaseModel]] = CityRow

    @override
    def _make(self) -> None:
        rows = _load_cities(self.version.value.id)
        self.save_arrow(pa.Table.from_pylist(rows))

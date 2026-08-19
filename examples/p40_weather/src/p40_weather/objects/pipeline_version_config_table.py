"""``PipelineVersionConfigTable``: key-value snapshot of the active version's fields."""

from dataclasses import asdict
from enum import Enum
from typing import (
    ClassVar,
    override,
)

import p40_flowbase as fb
import pyarrow as pa
import pydantic as pyd

from p40_weather.objects.versions import (
    SUPPORTED_VERSIONS,
    narrow_version,
)


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
class PipelineVersionConfigTable(fb.Table):
    """Snapshot of the active ``WeatherVersion``'s fields as key-value rows.

    Useful for downstream debugging and audit: persists what the version
    metadata looked like at run time, in the same parquet folder layout
    as the rest of the pipeline. Picks up new ``WeatherVersion`` fields
    automatically because it iterates ``dataclasses.asdict``.
    """

    id: ClassVar[str] = "pipeline_version_config_table"
    description: ClassVar[str] = "Active WeatherVersion fields, key-value rows."
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    row_schema: ClassVar[type[pyd.BaseModel]] = VersionConfigRow

    @override
    def _make(self) -> None:
        wv = narrow_version(self.version)
        rows = [{"key": k, "value": str(v)} for k, v in asdict(wv).items()]
        self.save_arrow(pa.Table.from_pylist(rows))

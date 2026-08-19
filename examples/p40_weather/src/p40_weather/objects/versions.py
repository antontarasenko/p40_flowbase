"""Version metadata shared by every p40_weather ``DataObject``.

The one module under ``objects/`` that is not a data object: it holds
the per-version parameters, the version enum, and the narrowing helper
that every stage imports.
"""

from dataclasses import dataclass
from enum import Enum

import p40_flowbase as fb


@dataclass(frozen=True)
class WeatherVersion(fb.DataObjectVersion):
    """Per-version pipeline parameters.

    Holds only declarative knobs. The per-version city catalog lives
    in its own ``DataObject`` (``ManualInputCitiesTable``) sourced from
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


SUPPORTED_VERSIONS: tuple[Enum, ...] = (
    WeatherVersions.MAIN,
    WeatherVersions.BACKFILL_2025,
)


def narrow_version(version: Enum) -> WeatherVersion:
    """Narrow ``self.version`` (typed as ``Enum``) to ``WeatherVersion``."""
    value = version.value
    if not isinstance(value, WeatherVersion):
        msg = f"Expected WeatherVersion, got {type(value).__name__}"
        raise TypeError(msg)
    return value

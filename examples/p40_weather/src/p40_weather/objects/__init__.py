"""DataObject subclasses for the p40_weather pipeline.

All pipeline stages — plus their version metadata — live in
:mod:`p40_weather.objects.weather`. This module re-exports them for
the Dagster ``definitions``.
"""

from p40_weather.objects.weather import (
    CityRow,
    HourlyRow,
    NarrativeRow,
    SummaryRow,
    VersionConfigRow,
    WeatherCityNarrativeAgentDB,
    WeatherCityNarrativeTable,
    WeatherContextFiles,
    WeatherDoc,
    WeatherFigure,
    WeatherHourlyTable,
    WeatherHTTPDB,
    WeatherInputCities,
    WeatherResponseFiles,
    WeatherSummaryTable,
    WeatherVersion,
    WeatherVersionConfig,
    WeatherVersions,
)

__all__ = [
    "CityRow",
    "HourlyRow",
    "NarrativeRow",
    "SummaryRow",
    "VersionConfigRow",
    "WeatherCityNarrativeAgentDB",
    "WeatherCityNarrativeTable",
    "WeatherContextFiles",
    "WeatherDoc",
    "WeatherFigure",
    "WeatherHTTPDB",
    "WeatherHourlyTable",
    "WeatherInputCities",
    "WeatherResponseFiles",
    "WeatherSummaryTable",
    "WeatherVersion",
    "WeatherVersionConfig",
    "WeatherVersions",
]

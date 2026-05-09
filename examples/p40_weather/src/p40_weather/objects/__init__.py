"""DataObject subclasses for the p40_weather pipeline.

All six pipeline stages — plus their version metadata — live in
:mod:`p40_weather.objects.weather`. This module re-exports them for
the Dagster ``definitions``.
"""

from p40_weather.objects.weather import (
    HourlyRow,
    NarrativeRow,
    SummaryRow,
    WeatherCityNarrativeAgentDB,
    WeatherCityNarrativeTable,
    WeatherDoc,
    WeatherFigure,
    WeatherHourlyTable,
    WeatherHTTPDB,
    WeatherResponseFiles,
    WeatherSummaryTable,
    WeatherVersion,
    WeatherVersions,
)

__all__ = [
    "HourlyRow",
    "NarrativeRow",
    "SummaryRow",
    "WeatherCityNarrativeAgentDB",
    "WeatherCityNarrativeTable",
    "WeatherDoc",
    "WeatherFigure",
    "WeatherHTTPDB",
    "WeatherHourlyTable",
    "WeatherResponseFiles",
    "WeatherSummaryTable",
    "WeatherVersion",
    "WeatherVersions",
]

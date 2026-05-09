"""Dagster ``Definitions`` for the p40_weather pipeline.

Run with::

    cd examples/p40_weather
    pip install -e .
    dg dev -m p40_weather.definitions
"""

import dagster as dg
import p40_flowbase as fb

from p40_weather.config import settings
from p40_weather.objects import (
    WeatherCityNarrativeAgentDB,
    WeatherCityNarrativeTable,
    WeatherDoc,
    WeatherFigure,
    WeatherHourlyTable,
    WeatherHTTPDB,
    WeatherInputCities,
    WeatherResponseFiles,
    WeatherSummaryTable,
    WeatherVersionConfig,
    WeatherVersions,
)

# Apply settings to framework + agent state at definitions-load time.
fb.DataObject.set_local_data(settings.local_data)
WeatherCityNarrativeAgentDB.set_api_keys(
    anthropic_api_key=settings.anthropic_api_key,
)

partitions = fb.partitions_from_versions(
    (WeatherVersions.MAIN, WeatherVersions.BACKFILL_2025),
)
common = {
    "partitions_def": partitions,
    "version_enum_class": WeatherVersions,
}

version_config = fb.asset(WeatherVersionConfig, **common)
cities = fb.asset(WeatherInputCities, **common)
http_db = fb.asset(WeatherHTTPDB, deps=[cities], **common)
files = fb.asset(WeatherResponseFiles, deps=[http_db], **common)
hourly = fb.asset(WeatherHourlyTable, deps=[files], **common)
summary = fb.asset(WeatherSummaryTable, deps=[hourly], **common)
narrative_db = fb.asset(WeatherCityNarrativeAgentDB, deps=[summary], **common)
narrative = fb.asset(
    WeatherCityNarrativeTable,
    deps=[narrative_db],
    **common,
)
figure = fb.asset(WeatherFigure, deps=[summary], **common)
doc = fb.asset(
    WeatherDoc,
    deps=[figure, summary, narrative],
    **common,
)

defs = dg.Definitions(
    assets=[
        version_config,
        cities,
        http_db,
        files,
        hourly,
        summary,
        narrative_db,
        narrative,
        figure,
        doc,
    ],
    resources={"replace": fb.ReplaceResource()},
)

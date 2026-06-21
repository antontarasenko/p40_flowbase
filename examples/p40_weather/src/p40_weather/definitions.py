"""Dagster ``Definitions`` for the p40_weather pipeline.

DAG topology (deps, group, convert formats, retries) is declared on each
``DataObject`` subclass with the ``@fb.asset(...)`` decorator in
``objects/weather.py``. ``fb.assets_from_module`` discovers every class
the decorator registered in the ``p40_weather.objects`` package via the
``DagsterAssetWiring._registry``, so this file owns only: settings
application and resources.
"""

import dagster as dg
import p40_flowbase as fb

from p40_weather import objects
from p40_weather.config import settings
from p40_weather.objects import (
    WeatherCityNarrativeAgentDB,
    WeatherVersions,
)

# Apply settings to framework + agent state at definitions-load time.
fb.DataObject.set_local_data(settings.local_data)
WeatherCityNarrativeAgentDB.set_api_keys(
    anthropic_api_key=settings.anthropic_api_key,
)

defs = dg.Definitions(
    assets=fb.assets_from_module(
        objects,
        partitions_def=fb.partitions_from_versions(
            (WeatherVersions.MAIN, WeatherVersions.BACKFILL_2025),
        ),
        version_enum_class=WeatherVersions,
    ),
    resources={
        "replace": fb.ReplaceResource(),
        "convert_formats": fb.ConvertFormatsResource(),
    },
)

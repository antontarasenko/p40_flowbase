"""DataObject subclasses for the p40_weather pipeline.

One data object per module: each pipeline stage lives in its own file
under ``objects/``, named after the object, together with its row model
and any generated audit tables. ``versions`` is the one support module,
holding the version metadata every stage imports. Importing this package
imports every submodule, which registers each ``@fb.asset`` class for
``fb.assets_from_module`` discovery.
"""

from p40_weather.objects.anthropic_city_narrative_agent_db import (
    AnthropicAgentTaskExtra,
    AnthropicAgentTaskGroup,
    AnthropicCityNarrativeAgentDB,
)
from p40_weather.objects.anthropic_city_narrative_table import (
    NarrativeRow,
    AnthropicCityNarrativeTable,
)
from p40_weather.objects.manual_context_files import ManualContextFiles
from p40_weather.objects.weather_report_doc import WeatherReportDoc
from p40_weather.objects.open_meteo_city_temp_mean_figure import OpenMeteoCityTempMeanFigure
from p40_weather.objects.open_meteo_city_hourly_table import (
    HourlyRow,
    OpenMeteoCityHourlyTable,
)
from p40_weather.objects.open_meteo_forecast_http_db import (
    OpenMeteoForecastHTTPDB,
    OpenMeteoHTTPRequestExtra,
    OpenMeteoHTTPRequestGroup,
)
from p40_weather.objects.manual_input_cities_table import (
    CityRow,
    ManualInputCitiesTable,
)
from p40_weather.objects.open_meteo_forecast_response_files import OpenMeteoForecastResponseFiles
from p40_weather.objects.open_meteo_city_summary_table import (
    SummaryRow,
    OpenMeteoCitySummaryTable,
)
from p40_weather.objects.pipeline_version_config_table import (
    VersionConfigRow,
    PipelineVersionConfigTable,
)
from p40_weather.objects.versions import (
    WeatherVersion,
    WeatherVersions,
)

__all__ = [
    "CityRow",
    "HourlyRow",
    "NarrativeRow",
    "SummaryRow",
    "VersionConfigRow",
    "AnthropicAgentTaskExtra",
    "AnthropicAgentTaskGroup",
    "AnthropicCityNarrativeAgentDB",
    "AnthropicCityNarrativeTable",
    "ManualContextFiles",
    "WeatherReportDoc",
    "OpenMeteoCityTempMeanFigure",
    "OpenMeteoForecastHTTPDB",
    "OpenMeteoHTTPRequestExtra",
    "OpenMeteoHTTPRequestGroup",
    "OpenMeteoCityHourlyTable",
    "ManualInputCitiesTable",
    "OpenMeteoForecastResponseFiles",
    "OpenMeteoCitySummaryTable",
    "WeatherVersion",
    "PipelineVersionConfigTable",
    "WeatherVersions",
]

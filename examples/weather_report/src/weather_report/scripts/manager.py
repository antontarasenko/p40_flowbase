#!/usr/bin/env python3
"""Manager CLI for weather_report data objects."""

from p40_flowbase import (
    BaseDataObjectManager,
    apply_style,
)

from weather_report.config import settings
from weather_report.data import (
    AverageTemperatureTable,
    CitySample,
    ForecastComposite,
    HourlyForecastTable,
    ReportMetadataDB,
    ReportTranscriptionDB,
    TemperatureFigure,
    WeatherHTTPRequestsDB,
    WeatherReportDocument,
)


class WeatherReportManager(BaseDataObjectManager):
    """Manager for weather_report data objects."""

    OBJECTS = {
        CitySample.id: CitySample,
        WeatherHTTPRequestsDB.id: WeatherHTTPRequestsDB,
        ForecastComposite.id: ForecastComposite,
        HourlyForecastTable.id: HourlyForecastTable,
        AverageTemperatureTable.id: AverageTemperatureTable,
        TemperatureFigure.id: TemperatureFigure,
        WeatherReportDocument.id: WeatherReportDocument,
        ReportTranscriptionDB.id: ReportTranscriptionDB,
        ReportMetadataDB.id: ReportMetadataDB,
    }

    app_name = "weather_report_manager"
    app_help = "Manage weather_report data objects"

    @property
    def data_local_tmp(self) -> str:
        return settings.data_local_tmp

    @property
    def anthropic_api_key(self) -> str | None:
        return settings.anthropic_api_key

    @property
    def google_api_key(self) -> str | None:
        return settings.google_api_key

    @property
    def openai_api_key(self) -> str | None:
        return settings.openai_api_key

    def configure_styles(self) -> None:
        apply_style("style_1")


manager = WeatherReportManager()
app = manager.app


if __name__ == "__main__":
    manager.run()

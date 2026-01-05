"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
import json
import pickle
import uuid
from datetime import (
    UTC,
    datetime,
)
from enum import Enum
from typing import (
    Any,
    List,
)

import matplotlib.pyplot as plt
import pandas as pd
import pydantic as pyd
from sqlmodel import (
    Field,
    SQLModel,
)

import p40_flowbase as fb

from weather_report.config import settings


class CoastVersions(Enum):
    EAST_COAST = fb.DataObjectVersion(
        id="east_coast",
        name="East Coast",
        description="East Coast cities (New York, Boston, Miami, Washington)",
    )
    WEST_COAST = fb.DataObjectVersion(
        id="west_coast",
        name="West Coast",
        description="West Coast cities (San Francisco, Seattle, Los Angeles, Portland)",
    )


class MainVersions(Enum):
    MAIN = fb.DataObjectVersion(
        id="main",
        name="Main",
        description="Main version",
    )


class CitySampleStruct(pyd.BaseModel):
    version: str = pyd.Field(
        title="Version",
        description="Data version identifier (e.g., east_coast, west_coast)",
        json_schema_extra={"units": "text"},
    )
    name: str = pyd.Field(
        title="City Name",
        description="Name of the city",
        json_schema_extra={"units": "text"},
    )
    lat: float = pyd.Field(
        title="Latitude",
        description="Latitude coordinate of the city",
        json_schema_extra={"units": "degrees"},
    )
    lon: float = pyd.Field(
        title="Longitude",
        description="Longitude coordinate of the city",
        json_schema_extra={"units": "degrees"},
    )


class CitySample(fb.TableDataObject):
    id: str = "city_sample"
    description: str = "Sample of cities for weather data collection"
    supported_versions = tuple(CoastVersions)
    schema = CitySampleStruct

    def _cities_east_coast(self):
        """Return list of East Coast cities."""
        return [
            {"version": "east_coast", "name": "New York", "lat": 40.7128, "lon": -74.0060},
            {"version": "east_coast", "name": "Boston", "lat": 42.3601, "lon": -71.0589},
            {"version": "east_coast", "name": "Miami", "lat": 25.7617, "lon": -80.1918},
            {"version": "east_coast", "name": "Washington", "lat": 38.9072, "lon": -77.0369},
        ]

    def _cities_west_coast(self):
        """Return list of West Coast cities."""
        return [
            {"version": "west_coast", "name": "San Francisco", "lat": 37.7749, "lon": -122.4194},
            {"version": "west_coast", "name": "Seattle", "lat": 47.6062, "lon": -122.3321},
            {"version": "west_coast", "name": "Los Angeles", "lat": 34.0522, "lon": -118.2437},
            {"version": "west_coast", "name": "Portland", "lat": 45.5152, "lon": -122.6784},
        ]

    def _make_default(self):
        """Create sample table with cities for the specified version."""
        if self.version == CoastVersions.EAST_COAST:
            cities = self._cities_east_coast()
        elif self.version == CoastVersions.WEST_COAST:
            cities = self._cities_west_coast()
        else:
            raise ValueError(f"Unknown version '{self.version.value.id}'")

        df = pd.DataFrame(cities)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)


class WeatherHTTPRequestGroup(SQLModel, table=True):
    __tablename__ = "http_request_groups"
    __table_args__ = {"extend_existing": True}

    http_request_group_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_class: str


class WeatherHTTPRequestsDB(fb.HTTPRequestsDBMixin, fb.DBDataObject):
    id: str = "weather_http_requests_db"
    description: str = "Database for logging and executing HTTP requests to weather APIs"
    supported_versions = tuple(MainVersions)
    schema: List[Any] = [WeatherHTTPRequestGroup, fb.HTTPRequestExtra, fb.HTTPRequest]

    async def _populate_points_requests(self, sample_version: CoastVersions, group_id: uuid.UUID):
        """Populate points requests for a specific sample version."""
        sample_obj = CitySample(sample_version)

        if not sample_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            sample_obj.make(replace=False)

        locations_df = sample_obj.pdf

        headers = json.dumps({"User-Agent": "example@example.com"})

        points_requests = []
        for _, location in locations_df.iterrows():
            lat = location["lat"]
            lon = location["lon"]
            points_url = f"https://api.weather.gov/points/{lat},{lon}"

            points_requests.append(
                {
                    "request_url": points_url,
                    "request_method": "GET",
                    "request_headers": headers,
                    "http_request_group_id": group_id,
                }
            )

        await self._add_http_requests(points_requests)

    async def _populate_http_requests(self) -> uuid.UUID:
        """Populate database with API requests for all sample versions."""
        group = WeatherHTTPRequestGroup(created_by_class=self.__class__.__name__)

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        await self._populate_points_requests(CoastVersions.EAST_COAST, group.http_request_group_id)
        await self._populate_points_requests(CoastVersions.WEST_COAST, group.http_request_group_id)

        return group.http_request_group_id

    async def _populate_forecast_requests(self, sample_version: CoastVersions) -> uuid.UUID:
        """Populate forecast requests based on completed points requests."""
        from sqlmodel import select

        sample_obj = CitySample(sample_version)
        if not sample_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            sample_obj.make(replace=False)

        locations_df = sample_obj.pdf

        expected_points_urls = set()
        for _, location in locations_df.iterrows():
            lat = location["lat"]
            lon = location["lon"]
            points_url = f"https://api.weather.gov/points/{lat},{lon}"
            expected_points_urls.add(points_url)

        async with self.session_factory() as session:
            points_statement = select(fb.HTTPRequest).where(
                fb.HTTPRequest.response_status == 200,
                fb.HTTPRequest.request_url.in_(expected_points_urls),
                fb.HTTPRequest.requested_at_utc.is_not(None),
            )
            points_result = await session.exec(points_statement)
            points_responses = points_result.all()

        headers = json.dumps({"User-Agent": "example@example.com"})
        group = WeatherHTTPRequestGroup(created_by_class=self.__class__.__name__)

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        forecast_requests = []
        for points_log in points_responses:
            if points_log.response_body_text:
                try:
                    points_data = json.loads(points_log.response_body_text)
                    properties = points_data.get("properties", {})
                    forecast_hourly_url = properties.get("forecastHourly")

                    if forecast_hourly_url:
                        forecast_requests.append(
                            {
                                "request_url": forecast_hourly_url,
                                "request_method": "GET",
                                "request_headers": headers,
                                "http_request_group_id": group.http_request_group_id,
                            }
                        )
                except json.JSONDecodeError:
                    continue

        await self._add_http_requests(forecast_requests)

        return group.http_request_group_id


class ForecastComposite(fb.CompositeDataObject):
    id: str = "forecast_composite"
    description: str = "Composite weather data files extracted from HTTP requests database"
    supported_versions = tuple(CoastVersions)

    def _make_default(self):
        """Extract data from database and save to files directory."""
        files_dir = self.path_to_format(fb.CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)

        asyncio.run(self._extract_from_db(files_dir))

    async def _extract_from_db(self, files_dir):
        """Extract forecast data from database."""
        requests_db = WeatherHTTPRequestsDB(MainVersions.MAIN)

        if not requests_db.path_to_format(fb.DBFormat.SQLITE).exists():
            await requests_db.make_async()

        sample_obj = CitySample(self.version)
        if not sample_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            sample_obj.make(replace=False)

        locations_df = sample_obj.pdf

        expected_points_urls = set()
        for _, location in locations_df.iterrows():
            lat = location["lat"]
            lon = location["lon"]
            points_url = f"https://api.weather.gov/points/{lat},{lon}"
            expected_points_urls.add(points_url)

        from sqlmodel import select

        async with requests_db.session_factory() as session:
            points_statement = select(fb.HTTPRequest).where(
                fb.HTTPRequest.request_url.in_(expected_points_urls),
            )
            points_result = await session.exec(points_statement)
            existing_points = points_result.all()

        if len(existing_points) == 0:
            await requests_db._populate_http_requests()
            await requests_db.execute(rate_limit=5.0, rate_period=1.0)

        async with requests_db.session_factory() as session:
            pending_statement = select(fb.HTTPRequest).where(
                fb.HTTPRequest.requested_at_utc.is_(None)
            )
            pending_result = await session.exec(pending_statement)
            pending_requests = pending_result.all()

        if len(pending_requests) > 0:
            await requests_db.execute(rate_limit=5.0, rate_period=1.0)

        async with requests_db.session_factory() as session:
            forecast_statement = select(fb.HTTPRequest).where(
                fb.HTTPRequest.request_url.like("https://api.weather.gov/gridpoints/%/forecast/hourly"),
            )
            forecast_result = await session.exec(forecast_statement)
            existing_forecasts = forecast_result.all()

        if len(existing_forecasts) == 0:
            await requests_db._populate_forecast_requests(self.version)
            await requests_db.execute(rate_limit=5.0, rate_period=1.0)

        valid_points_urls = expected_points_urls

        async with requests_db.session_factory() as session:
            points_statement = select(fb.HTTPRequest).where(
                fb.HTTPRequest.response_status == 200,
                fb.HTTPRequest.request_url.like("https://api.weather.gov/points/%"),
                fb.HTTPRequest.requested_at_utc.is_not(None),
            )
            points_result = await session.exec(points_statement)
            all_points_responses = points_result.all()

            forecast_statement = select(fb.HTTPRequest).where(
                fb.HTTPRequest.response_status == 200,
                fb.HTTPRequest.request_url.like("https://api.weather.gov/gridpoints/%/forecast/hourly"),
                fb.HTTPRequest.requested_at_utc.is_not(None),
            )
            forecast_result = await session.exec(forecast_statement)
            forecast_responses = forecast_result.all()

        points_to_location = {}
        for points_log in all_points_responses:
            if points_log.request_url not in valid_points_urls:
                continue

            if points_log.response_body_text:
                try:
                    points_data = json.loads(points_log.response_body_text)
                    forecast_url = points_data.get("properties", {}).get("forecastHourly")

                    properties = points_data.get("properties", {})
                    city = properties.get("relativeLocation", {}).get("properties", {}).get("city", "Unknown")
                    state = properties.get("relativeLocation", {}).get("properties", {}).get("state", "Unknown")

                    if forecast_url and city != "Unknown" and state != "Unknown":
                        points_to_location[forecast_url] = (city, state)

                except json.JSONDecodeError:
                    continue

        for forecast_log in forecast_responses:
            if forecast_log.response_body_text and forecast_log.request_url in points_to_location:
                try:
                    forecast_data = json.loads(forecast_log.response_body_text)
                    city, state = points_to_location[forecast_log.request_url]

                    filename = f"{city}-{state}.json"
                    filepath = files_dir / filename

                    with open(filepath, "w") as f:
                        json.dump(forecast_data, f, indent=2)

                except json.JSONDecodeError:
                    continue

        await requests_db.close()


class HourlyForecastStruct(pyd.BaseModel):
    city: str = pyd.Field(
        title="City",
        description="Name of the city where the weather forecast is located",
        json_schema_extra={"units": "text"},
    )
    state: str = pyd.Field(
        title="State",
        description="Two-letter state abbreviation",
        json_schema_extra={"units": "text"},
    )
    hour: str = pyd.Field(
        title="Hour",
        description="ISO 8601 timestamp for the forecast hour",
        json_schema_extra={"units": "datetime"},
    )
    temperature: float = pyd.Field(
        title="Temperature",
        description="Forecasted temperature value",
        json_schema_extra={"units": "°F"},
    )


class HourlyForecastTable(fb.TableDataObject):
    id: str = "hourly_forecast_table"
    description: str = "Hourly temperature forecast table by city and state"
    supported_versions = tuple(CoastVersions)
    schema = HourlyForecastStruct

    def _make_default(self):
        """Extract temperature data from weather files."""
        composite_obj = ForecastComposite(self.version)
        files_dir = composite_obj.path_to_format(fb.CompositeFormat.FILES)

        if not files_dir.exists() or not any(files_dir.glob("*.json")):
            composite_obj.make(replace=True)

        records = []

        for json_file in files_dir.glob("*.json"):
            filename = json_file.stem
            parts = filename.split("-")
            if len(parts) < 2:
                continue

            city = parts[0]
            state = parts[1]

            with open(json_file, "r") as f:
                data = json.load(f)

            periods = data.get("properties", {}).get("periods", [])

            for period in periods:
                hour = period.get("startTime")
                temperature = period.get("temperature")

                if hour and temperature is not None:
                    records.append(
                        {
                            "city": city,
                            "state": state,
                            "hour": hour,
                            "temperature": float(temperature),
                        }
                    )

        df = pd.DataFrame(records)
        df = df.convert_dtypes(dtype_backend="pyarrow")
        df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)


class AverageTemperatureStruct(pyd.BaseModel):
    city: str = pyd.Field(
        title="City",
        description="Name of the city where the weather forecast is located",
        json_schema_extra={"units": "text"},
    )
    state: str = pyd.Field(
        title="State",
        description="Two-letter state abbreviation",
        json_schema_extra={"units": "text"},
    )
    avg_temperature: float = pyd.Field(
        title="Average Temperature",
        description="Mean temperature across all forecast hours for the city",
        json_schema_extra={"units": "°F"},
    )


class AverageTemperatureTable(fb.TableDataObject):
    id: str = "average_temperature_table"
    description: str = "Aggregated average temperature by city and state"
    supported_versions = tuple(CoastVersions)
    schema = AverageTemperatureStruct

    def _make_default(self):
        """Aggregate temperature data by city and state."""
        table_obj = HourlyForecastTable(self.version)

        if not table_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            table_obj.make(replace=False)

        df = table_obj.pdf

        agg_df = (
            df.groupby(["city", "state"])
            .agg({"temperature": "mean"})
            .reset_index()
        )
        agg_df.columns = ["city", "state", "avg_temperature"]
        agg_df = agg_df.convert_dtypes(dtype_backend="pyarrow")

        agg_df.to_parquet(self.path_to_format(fb.TableFormat.PARQUET), index=False)


class TemperatureFigure(fb.FigureDataObject):
    id: str = "temperature_figure"
    description: str = "Temperature time series figure by city"
    supported_versions = tuple(CoastVersions)

    def _make_default(self):
        """Create temperature time series plot."""
        import pyarrow as pa

        table_obj = HourlyForecastTable(self.version)

        if not table_obj.path_to_format(fb.TableFormat.PARQUET).exists():
            table_obj.make(replace=False)

        df = table_obj.pdf

        df["datetime"] = pd.to_datetime(
            df["hour"],
            utc=True,
        ).astype(pd.ArrowDtype(pa.timestamp("ns", tz="UTC")))

        fig, ax = plt.subplots()

        for (city, state), group in df.groupby(["city", "state"]):
            group_sorted = group.sort_values("datetime")
            ax.plot(
                group_sorted["datetime"],
                group_sorted["temperature"],
                marker="o",
                label=f"{city}, {state}",
                linewidth=2,
                markersize=4,
            )

        ax.set_xlabel("Time")
        ax.set_ylabel("Temperature (°F)")
        ax.set_title("Hourly Temperature Forecast by City")
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()

        with open(self.path_to_format(fb.FigureFormat.PKL), "wb") as f:
            pickle.dump(fig, f)


class WeatherReportDocument(fb.DocumentDataObject):
    id: str = "weather_report_document"
    description: str = "Weather forecast report document with tables and figures"
    template: str = "weather_report.md.jinja"
    supported_versions = tuple(MainVersions)

    def _make_data(self):
        """Populate data dict with aggregate table and figure for both coasts."""
        east_agg_table_obj = AverageTemperatureTable(CoastVersions.EAST_COAST)
        west_agg_table_obj = AverageTemperatureTable(CoastVersions.WEST_COAST)
        east_figure_obj = TemperatureFigure(CoastVersions.EAST_COAST)
        west_figure_obj = TemperatureFigure(CoastVersions.WEST_COAST)

        if not east_agg_table_obj.path_to_format(east_agg_table_obj.make_format).exists():
            east_agg_table_obj.make()
        if not east_agg_table_obj.path_to_format(fb.TableFormat.JSON).exists():
            east_agg_table_obj.convert(fb.TableFormat.JSON)
        with open(east_agg_table_obj.path_to_format(fb.TableFormat.JSON), "r") as f:
            east_agg_table_data = json.load(f)

        if not west_agg_table_obj.path_to_format(west_agg_table_obj.make_format).exists():
            west_agg_table_obj.make()
        if not west_agg_table_obj.path_to_format(fb.TableFormat.JSON).exists():
            west_agg_table_obj.convert(fb.TableFormat.JSON)
        with open(west_agg_table_obj.path_to_format(fb.TableFormat.JSON), "r") as f:
            west_agg_table_data = json.load(f)

        if not east_figure_obj.path_to_format(east_figure_obj.make_format).exists():
            east_figure_obj.make()
        if not east_figure_obj.path_to_format(fb.FigureFormat.SVG).exists():
            east_figure_obj.convert(fb.FigureFormat.SVG)
        east_figure_path = east_figure_obj.path_to_format(fb.FigureFormat.SVG)

        if not west_figure_obj.path_to_format(west_figure_obj.make_format).exists():
            west_figure_obj.make()
        if not west_figure_obj.path_to_format(fb.FigureFormat.SVG).exists():
            west_figure_obj.convert(fb.FigureFormat.SVG)
        west_figure_path = west_figure_obj.path_to_format(fb.FigureFormat.SVG)

        made_at = datetime.now()
        made_on_str = f"{made_at.strftime('%B')} {made_at.day}, {made_at.year}"

        self.data = {
            "beamer_theme": fb.STYLES[settings.style]["beamer"]["theme"],
            "east_coast_aggregate_table": east_agg_table_data,
            "east_coast_figure_path": str(east_figure_path),
            "west_coast_aggregate_table": west_agg_table_data,
            "west_coast_figure_path": str(west_figure_path),
            "made_on": made_on_str,
        }


class WeatherLLMRequestGroup(SQLModel, table=True):
    __tablename__ = "llm_request_groups"
    __table_args__ = {"extend_existing": True}

    llm_request_group_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by_class: str


class ReportTranscriptionDB(fb.LLMRequestsDBMixin, fb.HTTPRequestsDBMixin, fb.DBDataObject):
    """Database for LLM requests, including PDF transcription tasks."""

    id: str = "report_transcription_db"
    description: str = "Database for logging and executing LLM transcription requests"
    schema: List[Any] = [
        WeatherLLMRequestGroup,
        fb.LLMRequestExtra,
        fb.LLMFile,
        fb.LLMRequest,
        WeatherHTTPRequestGroup,
        fb.HTTPRequestExtra,
        fb.HTTPRequest,
    ]
    supported_versions = tuple(MainVersions)

    async def _populate_llm_requests(self) -> uuid.UUID:
        """Populate database with LLM transcription request."""
        llm_request = await self._transcribe_document(
            document_version=self.version,
            transcription_format="md",
        )
        return llm_request.llm_request_group_id

    async def _transcribe_document(
        self,
        document_version: Enum = MainVersions.MAIN,
        transcription_format: str = "md",
    ) -> fb.LLMRequest:
        """Transcribe a WeatherReportDocument PDF using an LLM."""
        import pathlib

        from p40_flowbase.helpers import render_prompt_template

        document = WeatherReportDocument(document_version)
        pdf_path = document.path_to_format(fb.DocumentFormat.PDF)

        if not pdf_path.exists():
            if not document.path_to_format(document.make_format).exists():
                document.make()
            document.convert(fb.DocumentFormat.PDF)

        llm_file = await self._add_llm_file(
            file_path=pathlib.Path(pdf_path),
            data_object_class_name=document.__class__.__name__,
            data_object_id=document.id,
            data_object_version=document.version.value.id,
            data_object_format="pdf",
        )

        group = WeatherLLMRequestGroup(
            created_by_class=self.__class__.__name__,
        )

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        system_prompt = render_prompt_template(
            template_name="weather_report_transcription.md.jinja",
            project_package="weather_report.prompts",
            transcription_format=transcription_format,
        )

        llm_requests = await self._add_llm_requests([{
            "model": fb.LLMModels.GEMINI_2_5_FLASH_LITE,
            "system_prompt": system_prompt,
            "user_prompt": "Please transcribe the content of this PDF document.",
            "temperature": 0.1,
            "attachments": [str(llm_file.llm_file_id)],
            "llm_request_group_id": group.llm_request_group_id,
        }])

        return llm_requests[0]


class ExtractedReportMetadata(pyd.BaseModel):
    """Structured schema for document metadata extraction."""

    author: str = pyd.Field(
        description="Name of the document author or organization",
    )
    title: str = pyd.Field(
        description="Title of the document",
    )
    date: str = pyd.Field(
        description="Date when the document was created or published in format 'YYYY-MM-DD'. ",
    )


class ReportMetadataDB(fb.LLMRequestsDBMixin, fb.HTTPRequestsDBMixin, fb.DBDataObject):
    """Database for LLM requests with structured output extraction."""

    id: str = "report_metadata_db"
    description: str = "Database for logging and executing LLM metadata extraction requests"
    schema: List[Any] = [
        WeatherLLMRequestGroup,
        fb.LLMRequestExtra,
        fb.LLMFile,
        fb.LLMRequest,
        WeatherHTTPRequestGroup,
        fb.HTTPRequestExtra,
        fb.HTTPRequest,
    ]
    supported_versions = tuple(MainVersions)

    async def _populate_llm_requests(self) -> uuid.UUID:
        """Populate database with LLM metadata extraction request."""
        llm_request = await self._extract_metadata(
            document_version=self.version,
        )
        return llm_request.llm_request_group_id

    async def _extract_metadata(
        self,
        document_version: Enum = MainVersions.MAIN,
    ) -> fb.LLMRequest:
        """Extract metadata from a WeatherReportDocument HTML using structured output."""
        import pathlib

        from p40_flowbase.helpers import render_prompt_template

        document = WeatherReportDocument(document_version)
        html_path = document.path_to_format(fb.DocumentFormat.HTML)

        if not html_path.exists():
            if not document.path_to_format(document.make_format).exists():
                document.make()
            document.convert(fb.DocumentFormat.HTML)

        llm_file = await self._add_llm_file(
            file_path=pathlib.Path(html_path),
            data_object_class_name=document.__class__.__name__,
            data_object_id=document.id,
            data_object_version=document.version.value.id,
            data_object_format="html",
        )

        group = WeatherLLMRequestGroup(
            created_by_class=self.__class__.__name__,
        )

        async with self.session_factory() as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)

        system_prompt = render_prompt_template(
            template_name="weather_report_extraction.md.jinja",
            project_package="weather_report.prompts",
        )

        llm_requests = await self._add_llm_requests([{
            "model": fb.LLMModels.GEMINI_2_5_FLASH_LITE,
            "system_prompt": system_prompt,
            "user_prompt": "Please extract the metadata from this HTML document.",
            "temperature": 0.1,
            "attachments": [str(llm_file.llm_file_id)],
            "response_schema": ExtractedReportMetadata,
            "llm_request_group_id": group.llm_request_group_id,
        }])

        return llm_requests[0]

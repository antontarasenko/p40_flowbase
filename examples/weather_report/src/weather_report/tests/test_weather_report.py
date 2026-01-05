"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import os

import pandas as pd
import pytest

import p40_flowbase as fb
import weather_report.config as config
from weather_report.data import (
    AverageTemperatureTable,
    CitySample,
    CoastVersions,
    ExtractedReportMetadata,
    ForecastComposite,
    HourlyForecastTable,
    MainVersions,
    ReportMetadataDB,
    ReportTranscriptionDB,
    TemperatureFigure,
    WeatherHTTPRequestsDB,
    WeatherLLMRequestGroup,
)


def test_config_uses_temporary_directory():
    """Verify that tests use a temporary directory, not the production DATA_LOCAL_TMP."""
    env_data_local_tmp = os.environ.get("DATA_LOCAL_TMP")
    assert config.settings.data_local_tmp != env_data_local_tmp, \
        f"config.settings.data_local_tmp should be isolated from DATA_LOCAL_TMP env var"
    assert "pytest" in config.settings.data_local_tmp.lower() or "tmp" in config.settings.data_local_tmp.lower(), \
        f"config.settings.data_local_tmp should be a temporary directory"


class TestCitySample:
    """Tests for CitySample."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_sample_creates_all_formats(self, fmt):
        """Test that CitySample creates all formats."""
        sample = CitySample(CoastVersions.EAST_COAST)
        sample.make(replace=True)
        sample.convert(replace=True)

        format_path = sample.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_sample_has_rows(self):
        """Test that CitySample table has rows."""
        sample = CitySample(CoastVersions.EAST_COAST)
        sample.make(replace=True)
        df = sample.pdf

        assert len(df) > 0, "Sample table should have at least one row"
        assert "name" in df.columns, "Sample should have 'name' column"
        assert "lat" in df.columns, "Sample should have 'lat' column"
        assert "lon" in df.columns, "Sample should have 'lon' column"

    def test_sample_uses_pyarrow_dtypes(self):
        """Test that CitySample uses PyArrow dtypes."""
        sample = CitySample(CoastVersions.EAST_COAST)
        sample.make(replace=True)
        df = sample.pdf

        assert all(isinstance(dtype, pd.ArrowDtype) for dtype in df.dtypes), \
            "All columns should use PyArrow dtypes"


@pytest.mark.xdist_group(name="weather_db_dependent")
class TestWeatherHTTPRequestsDB:
    """Tests for WeatherHTTPRequestsDB."""

    @pytest.mark.asyncio
    async def test_db_creates_database(self):
        """Test that WeatherHTTPRequestsDB creates a database file."""
        db = WeatherHTTPRequestsDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        sqlite_path = db.path_to_format(fb.DBFormat.SQLITE)
        assert sqlite_path.exists(), "SQLite database file should exist"
        assert sqlite_path.stat().st_size > 0, "SQLite database should not be empty"

        await db.close()

    @pytest.mark.asyncio
    async def test_db_add_http_requests(self):
        """Test that WeatherHTTPRequestsDB can add HTTP requests."""
        from sqlmodel import select

        db = WeatherHTTPRequestsDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        sample = CitySample(CoastVersions.EAST_COAST)
        sample.make(replace=True)

        await db.populate()

        async with db.session_factory() as session:
            statement = select(fb.HTTPRequest)
            result = await session.exec(statement)
            requests = result.all()

        assert len(requests) > 0, "Should have added HTTP requests"

        await db.close()


@pytest.mark.xdist_group(name="weather_db_dependent")
class TestForecastComposite:
    """Tests for ForecastComposite."""

    @pytest.mark.parametrize("fmt", [
        fb.CompositeFormat.FILES,
        fb.CompositeFormat.ZIP,
        fb.CompositeFormat.TAR_ZST,
    ])
    def test_composite_creates_all_formats(self, weather_http_requests_db, fmt):
        """Test that ForecastComposite creates all formats."""
        composite = ForecastComposite(CoastVersions.EAST_COAST)
        composite.make(replace=True)
        composite.convert(replace=True)

        format_path = composite.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} should exist"

        if fmt == fb.CompositeFormat.FILES:
            assert format_path.is_dir(), f"{fmt.value} path should be a directory"
            json_files = list(format_path.glob("*.json"))
            assert len(json_files) > 0, "Should have created at least one JSON file"
            for json_file in json_files:
                assert json_file.stat().st_size > 0, f"{json_file.name} should not be empty"
        else:
            assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"


@pytest.mark.xdist_group(name="weather_db_dependent")
class TestHourlyForecastTable:
    """Tests for HourlyForecastTable."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_table_creates_all_formats(self, weather_http_requests_db, fmt):
        """Test that HourlyForecastTable creates all formats."""
        table = HourlyForecastTable(CoastVersions.EAST_COAST)
        table.make(replace=True)
        table.convert(replace=True)

        format_path = table.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_table_has_rows(self, weather_http_requests_db):
        """Test that HourlyForecastTable has rows."""
        table = HourlyForecastTable(CoastVersions.EAST_COAST)
        table.make(replace=True)
        df = table.pdf

        assert len(df) > 0, "Table should have at least one row"
        assert "city" in df.columns, "Table should have 'city' column"
        assert "state" in df.columns, "Table should have 'state' column"
        assert "hour" in df.columns, "Table should have 'hour' column"
        assert "temperature" in df.columns, "Table should have 'temperature' column"

    def test_table_uses_pyarrow_dtypes(self, weather_http_requests_db):
        """Test that HourlyForecastTable uses PyArrow dtypes."""
        table = HourlyForecastTable(CoastVersions.EAST_COAST)
        table.make(replace=True)
        df = table.pdf

        assert all(isinstance(dtype, pd.ArrowDtype) for dtype in df.dtypes), \
            "All columns should use PyArrow dtypes"


@pytest.mark.xdist_group(name="weather_db_dependent")
class TestAverageTemperatureTable:
    """Tests for AverageTemperatureTable."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_aggregate_table_creates_all_formats(self, weather_http_requests_db, fmt):
        """Test that AverageTemperatureTable creates all formats."""
        agg_table = AverageTemperatureTable(CoastVersions.EAST_COAST)
        agg_table.make(replace=True)
        agg_table.convert(replace=True)

        format_path = agg_table.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_aggregate_table_has_rows(self, weather_http_requests_db):
        """Test that AverageTemperatureTable has rows."""
        agg_table = AverageTemperatureTable(CoastVersions.EAST_COAST)
        agg_table.make(replace=True)
        df = agg_table.pdf

        assert len(df) > 0, "Aggregate table should have at least one row"
        assert "city" in df.columns, "Aggregate table should have 'city' column"
        assert "state" in df.columns, "Aggregate table should have 'state' column"
        assert "avg_temperature" in df.columns, "Should have 'avg_temperature' column"

    def test_aggregate_table_uses_pyarrow_dtypes(self, weather_http_requests_db):
        """Test that AverageTemperatureTable uses PyArrow dtypes."""
        agg_table = AverageTemperatureTable(CoastVersions.EAST_COAST)
        agg_table.make(replace=True)
        df = agg_table.pdf

        assert all(isinstance(dtype, pd.ArrowDtype) for dtype in df.dtypes), \
            "All columns should use PyArrow dtypes"


@pytest.mark.xdist_group(name="weather_db_dependent")
class TestTemperatureFigure:
    """Tests for TemperatureFigure."""

    @pytest.mark.parametrize("fmt", [
        fb.FigureFormat.PKL,
        fb.FigureFormat.PDF,
        fb.FigureFormat.PNG,
        fb.FigureFormat.SVG,
    ])
    def test_figure_creates_all_formats(self, weather_http_requests_db, fmt):
        """Test that TemperatureFigure creates all formats."""
        figure = TemperatureFigure(CoastVersions.EAST_COAST)
        figure.make(replace=True)
        figure.convert(replace=True)

        format_path = figure.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_figure_uses_pyarrow_datetime(self, weather_http_requests_db):
        """Test that TemperatureFigure converts datetime to PyArrow timestamp dtype."""
        import pyarrow as pa

        table = HourlyForecastTable(CoastVersions.EAST_COAST)
        table.make(replace=True)
        df = table.pdf

        datetime_col = pd.to_datetime(
            df["hour"],
            utc=True,
        ).astype(pd.ArrowDtype(pa.timestamp("ns", tz="UTC")))

        assert isinstance(datetime_col.dtype, pd.ArrowDtype), \
            "datetime column should use PyArrow dtype"
        assert pa.types.is_timestamp(datetime_col.dtype.pyarrow_dtype), \
            "datetime should be PyArrow timestamp type"


class TestReportTranscriptionDB:
    """Tests for ReportTranscriptionDB."""

    @pytest.mark.asyncio
    async def test_llm_db_creates_database(self):
        """Test that ReportTranscriptionDB creates a database file with all tables."""
        db = ReportTranscriptionDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        sqlite_path = db.path_to_format(fb.DBFormat.SQLITE)
        assert sqlite_path.exists(), "SQLite database file should exist"
        assert sqlite_path.stat().st_size > 0, "SQLite database should not be empty"

        await db.close()

    @pytest.mark.asyncio
    async def test_llm_db_add_llm_file(self):
        """Test that ReportTranscriptionDB can add LLM files."""
        import pathlib
        import shutil

        db = ReportTranscriptionDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        object_stem = "test_object-main"
        local_dir = pathlib.Path(config.settings.data_local_tmp) / object_stem
        local_dir.mkdir(parents=True, exist_ok=True)

        test_file = local_dir / f"{object_stem}.txt"
        test_file.write_text("Test content for LLM file")

        try:
            llm_file = await db._add_llm_file(
                file_path=test_file,
                data_object_class_name="TestClass",
                data_object_id="test_object",
                data_object_version="main",
                data_object_format="txt",
            )

            assert llm_file.llm_file_id is not None, "LLM file should have an ID"
            assert llm_file.name == test_file.name, "LLM file name should match"
            assert llm_file.size_bytes > 0, "LLM file should have size"
            assert llm_file.md5sum is not None, "LLM file should have md5sum"
            assert llm_file.data_object_class_name == "TestClass"
            assert llm_file.data_object_id == "test_object"
            assert llm_file.data_object_version == "main"
            assert llm_file.data_object_format == "txt"
        finally:
            if local_dir.exists():
                shutil.rmtree(local_dir)

        await db.close()

    @pytest.mark.asyncio
    async def test_llm_db_add_llm_requests(self):
        """Test that ReportTranscriptionDB can add LLM requests."""
        db = ReportTranscriptionDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        llm_requests = await db._add_llm_requests([{
            "model": fb.LLMModels.GEMINI_2_5_FLASH_LITE,
            "system_prompt": "You are a test assistant.",
            "user_prompt": "Hello, world!",
            "temperature": 0.5,
        }])

        assert len(llm_requests) == 1, "Should have created one LLM request"
        assert llm_requests[0].llm_request_id is not None
        assert llm_requests[0].model == fb.LLMModels.GEMINI_2_5_FLASH_LITE
        assert llm_requests[0].system_prompt == "You are a test assistant."
        assert llm_requests[0].user_prompt == "Hello, world!"
        assert llm_requests[0].temperature == 0.5
        assert llm_requests[0].requested_at_utc is None, "Request should not be executed yet"

        await db.close()


class TestReportMetadataDB:
    """Tests for ReportMetadataDB with structured output."""

    @pytest.mark.asyncio
    async def test_extraction_db_creates_database(self):
        """Test that ReportMetadataDB creates a database file with all tables."""
        db = ReportMetadataDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        sqlite_path = db.path_to_format(fb.DBFormat.SQLITE)
        assert sqlite_path.exists(), "SQLite database file should exist"
        assert sqlite_path.stat().st_size > 0, "SQLite database should not be empty"

        await db.close()

    @pytest.mark.asyncio
    async def test_extraction_db_add_llm_file_html(self):
        """Test that ReportMetadataDB can add HTML files."""
        import pathlib
        import shutil

        db = ReportMetadataDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        object_stem = "test_object-main"
        local_dir = pathlib.Path(config.settings.data_local_tmp) / object_stem
        local_dir.mkdir(parents=True, exist_ok=True)

        test_file = local_dir / f"{object_stem}.html"
        test_file.write_text("<html><body><h1>Test Document</h1></body></html>")

        try:
            llm_file = await db._add_llm_file(
                file_path=test_file,
                data_object_class_name="TestClass",
                data_object_id="test_object",
                data_object_version="main",
                data_object_format="html",
            )

            assert llm_file.llm_file_id is not None, "LLM file should have an ID"
            assert llm_file.name == test_file.name, "LLM file name should match"
            assert llm_file.size_bytes > 0, "LLM file should have size"
            assert llm_file.md5sum is not None, "LLM file should have md5sum"
            assert llm_file.data_object_format == "html", "Should be HTML format"
        finally:
            if local_dir.exists():
                shutil.rmtree(local_dir)

        await db.close()

    @pytest.mark.asyncio
    async def test_extraction_db_add_llm_requests_with_schema(self):
        """Test that ReportMetadataDB can add LLM requests with response_schema."""
        import json

        db = ReportMetadataDB(MainVersions.MAIN)
        await db.make_async(replace=True)

        llm_requests = await db._add_llm_requests([{
            "model": fb.LLMModels.GEMINI_2_5_FLASH_LITE,
            "system_prompt": "Extract metadata from the document.",
            "user_prompt": "Extract author, title, and date.",
            "temperature": 0.1,
            "response_schema": ExtractedReportMetadata,
        }])

        assert len(llm_requests) == 1, "Should have created one LLM request"
        assert llm_requests[0].llm_request_id is not None
        assert llm_requests[0].model == fb.LLMModels.GEMINI_2_5_FLASH_LITE
        assert llm_requests[0].response_schema is not None, "Should have response_schema"
        assert llm_requests[0].requested_at_utc is None, "Request should not be executed yet"

        schema = json.loads(llm_requests[0].response_schema)
        assert "properties" in schema, "Schema should have properties"
        assert "author" in schema["properties"], "Schema should have author field"
        assert "title" in schema["properties"], "Schema should have title field"
        assert "date" in schema["properties"], "Schema should have date field"

        await db.close()

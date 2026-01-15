"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import os

import pandas as pd
import pytest

import p40_flowbase as fb
import web_archive.config as config
from web_archive.data import (
    ClusterSpecs,
    URLSample,
    URLVersions,
    WMExtractedClusterSpecs,
    WMSnapshotContent,
    WMSnapshotContentDB,
    WMSnapshotContentLLMExtractionDB,
    WMSnapshotContentLLMRequestGroup,
    WMSnapshotFiles,
    WMSnapshotURLs,
    WMSnapshotURLsDB,
)


def test_config_uses_temporary_directory():
    """Verify that tests use a temporary directory, not the production DATA_LOCAL_TMP."""
    env_data_local_tmp = os.environ.get("DATA_LOCAL_TMP")
    assert config.settings.data_local_tmp != env_data_local_tmp, \
        f"config.settings.data_local_tmp should be isolated from DATA_LOCAL_TMP env var"
    assert "pytest" in config.settings.data_local_tmp.lower() or "tmp" in config.settings.data_local_tmp.lower(), \
        f"config.settings.data_local_tmp should be a temporary directory"


class TestURLSample:
    """Tests for URLSample."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_sample_creates_all_formats(self, fmt):
        """Test that URLSample creates all formats."""
        sample = URLSample(URLVersions.UNIS_1_TEST)
        sample.make(replace=True)
        sample.convert(replace=True)

        format_path = sample.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_sample_has_rows(self):
        """Test that URLSample table has rows."""
        sample = URLSample(URLVersions.UNIS_1_TEST)
        sample.make(replace=True)
        df = sample.pdf

        assert len(df) > 0, "Sample table should have at least one row"
        assert "org" in df.columns, "Sample should have 'org' column"
        assert "url" in df.columns, "Sample should have 'url' column"

    def test_sample_uses_pyarrow_dtypes(self):
        """Test that URLSample uses PyArrow dtypes."""
        sample = URLSample(URLVersions.UNIS_1_TEST)
        sample.make(replace=True)
        df = sample.pdf

        assert all(isinstance(dtype, pd.ArrowDtype) for dtype in df.dtypes), \
            "All columns should use PyArrow dtypes"


@pytest.mark.xdist_group(name="web_archive_db_dependent")
class TestWMSnapshotURLsDB:
    """Tests for WMSnapshotURLsDB."""

    @pytest.mark.asyncio
    async def test_db_creates_database(self):
        """Test that WMSnapshotURLsDB creates a database file."""
        db = WMSnapshotURLsDB(URLVersions.UNIS_1_TEST)
        await db.make_async(replace=True)

        sqlite_path = db.path_to_format(fb.DBFormat.SQLITE)
        assert sqlite_path.exists(), "SQLite database file should exist"
        assert sqlite_path.stat().st_size > 0, "SQLite database should not be empty"

        await db.close()

    @pytest.mark.asyncio
    async def test_db_add_http_requests(self):
        """Test that WMSnapshotURLsDB can add HTTP requests."""
        from sqlmodel import select

        db = WMSnapshotURLsDB(URLVersions.UNIS_1_TEST)
        await db.make_async(replace=True)

        sample = URLSample(URLVersions.UNIS_1_TEST)
        sample.make(replace=True)

        await db.populate()

        async with db.session_factory() as session:
            statement = select(fb.HTTPRequest)
            result = await session.exec(statement)
            requests = result.all()

        assert len(requests) > 0, "Should have added HTTP requests"

        await db.close()


@pytest.mark.xdist_group(name="web_archive_db_dependent")
class TestWMSnapshotURLs:
    """Tests for WMSnapshotURLs."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_table_creates_all_formats(self, wm_snapshot_urls_db, fmt):
        """Test that WMSnapshotURLs creates all formats."""
        table = WMSnapshotURLs(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        table.convert(replace=True)

        format_path = table.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_table_has_rows(self, wm_snapshot_urls_db):
        """Test that WMSnapshotURLs has rows."""
        table = WMSnapshotURLs(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        df = table.pdf

        assert len(df) > 0, "Table should have at least one row"
        assert "org" in df.columns, "Table should have 'org' column"
        assert "url" in df.columns, "Table should have 'url' column"
        assert "year" in df.columns, "Table should have 'year' column"
        assert "snapshot_url" in df.columns, "Table should have 'snapshot_url' column"

    def test_table_uses_pyarrow_dtypes(self, wm_snapshot_urls_db):
        """Test that WMSnapshotURLs uses PyArrow dtypes."""
        table = WMSnapshotURLs(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        df = table.pdf

        assert all(isinstance(dtype, pd.ArrowDtype) for dtype in df.dtypes), \
            "All columns should use PyArrow dtypes"


@pytest.mark.xdist_group(name="web_archive_db_dependent")
class TestWMSnapshotContentDB:
    """Tests for WMSnapshotContentDB."""

    @pytest.mark.asyncio
    async def test_db_creates_database(self, wm_snapshot_urls_db):
        """Test that WMSnapshotContentDB creates a database file."""
        db = WMSnapshotContentDB(URLVersions.UNIS_1_TEST)
        await db.make_async(replace=True)

        sqlite_path = db.path_to_format(fb.DBFormat.SQLITE)
        assert sqlite_path.exists(), "SQLite database file should exist"
        assert sqlite_path.stat().st_size > 0, "SQLite database should not be empty"

        await db.close()

    @pytest.mark.asyncio
    async def test_db_add_http_requests(self, wm_snapshot_content_db):
        """Test that WMSnapshotContentDB can add HTTP requests."""
        from sqlmodel import select

        db = WMSnapshotContentDB(URLVersions.UNIS_1_TEST)

        async with db.session_factory() as session:
            statement = select(fb.HTTPRequest)
            result = await session.exec(statement)
            requests = result.all()

        assert len(requests) > 0, "Should have added HTTP requests"

        await db.close()


@pytest.mark.xdist_group(name="web_archive_db_dependent")
class TestWMSnapshotContent:
    """Tests for WMSnapshotContent."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_table_creates_all_formats(self, wm_snapshot_content_db, fmt):
        """Test that WMSnapshotContent creates all formats."""
        table = WMSnapshotContent(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        table.convert(replace=True)

        format_path = table.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"
        assert format_path.stat().st_size > 0, f"{fmt.value} file should not be empty"

    def test_table_has_rows(self, wm_snapshot_content_db):
        """Test that WMSnapshotContent has rows."""
        table = WMSnapshotContent(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        df = table.pdf

        assert len(df) > 0, "Table should have at least one row"
        assert "org" in df.columns, "Table should have 'org' column"
        assert "url" in df.columns, "Table should have 'url' column"
        assert "year" in df.columns, "Table should have 'year' column"
        assert "snapshot_url" in df.columns, "Table should have 'snapshot_url' column"
        assert "snapshot_content" in df.columns, "Table should have 'snapshot_content' column"

    def test_table_uses_pyarrow_dtypes(self, wm_snapshot_content_db):
        """Test that WMSnapshotContent uses PyArrow dtypes."""
        table = WMSnapshotContent(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        df = table.pdf

        assert all(isinstance(dtype, pd.ArrowDtype) for dtype in df.dtypes), \
            "All columns should use PyArrow dtypes"


@pytest.mark.xdist_group(name="web_archive_db_dependent")
class TestWMSnapshotFiles:
    """Tests for WMSnapshotFiles."""

    def test_creates_files_directory(self, wm_snapshot_content_db):
        """Test that WMSnapshotFiles creates a files directory."""
        files_obj = WMSnapshotFiles(URLVersions.UNIS_1_TEST)
        files_obj.make(replace=True)

        files_dir = files_obj.path_to_format(fb.CompositeFormat.FILES)
        assert files_dir.exists(), "Files directory should exist"
        assert files_dir.is_dir(), "Files path should be a directory"

    def test_creates_html_files(self, wm_snapshot_content_db):
        """Test that WMSnapshotFiles creates HTML snapshot files."""
        files_obj = WMSnapshotFiles(URLVersions.UNIS_1_TEST)
        files_obj.make(replace=True)

        files_dir = files_obj.path_to_format(fb.CompositeFormat.FILES)
        html_files = list(files_dir.rglob("*.html"))

        assert len(html_files) > 0, "Should have created at least one HTML file"

    def test_html_files_not_empty(self, wm_snapshot_content_db):
        """Test that created HTML files are not empty."""
        files_obj = WMSnapshotFiles(URLVersions.UNIS_1_TEST)
        files_obj.make(replace=True)

        files_dir = files_obj.path_to_format(fb.CompositeFormat.FILES)
        html_files = list(files_dir.rglob("*.html"))

        for html_file in html_files:
            assert html_file.stat().st_size > 0, f"{html_file} should not be empty"

    def test_files_organized_by_org_url_year(self, wm_snapshot_content_db):
        """Test that files are organized in org/url/year directory structure."""
        files_obj = WMSnapshotFiles(URLVersions.UNIS_1_TEST)
        files_obj.make(replace=True)

        files_dir = files_obj.path_to_format(fb.CompositeFormat.FILES)
        html_files = list(files_dir.rglob("snapshot.html"))

        for html_file in html_files:
            rel_path = html_file.relative_to(files_dir)
            parts = rel_path.parts
            assert len(parts) == 4, f"Expected org/url/year/snapshot.html structure, got {rel_path}"
            assert parts[3] == "snapshot.html", f"File should be named snapshot.html"


class TestWMSnapshotContentLLMExtractionDB:
    """Tests for WMSnapshotContentLLMExtractionDB."""

    @pytest.mark.asyncio
    async def test_llm_db_creates_database(self):
        """Test that WMSnapshotContentLLMExtractionDB creates a database file."""
        db = WMSnapshotContentLLMExtractionDB(URLVersions.UNIS_1_TEST)
        await db.make_async(replace=True)

        sqlite_path = db.path_to_format(fb.DBFormat.SQLITE)
        assert sqlite_path.exists(), "SQLite database file should exist"
        assert sqlite_path.stat().st_size > 0, "SQLite database should not be empty"

        await db.close()

    @pytest.mark.asyncio
    async def test_llm_db_add_llm_requests(self):
        """Test that WMSnapshotContentLLMExtractionDB can add LLM requests."""
        db = WMSnapshotContentLLMExtractionDB(URLVersions.UNIS_1_TEST)
        await db.make_async(replace=True)

        llm_requests = await db._add_llm_requests([{
            "model": fb.LLMModels.GEMINI_2_5_FLASH_LITE,
            "system_prompt": "You are a test assistant.",
            "user_prompt": "Extract cluster specifications.",
            "temperature": 0.1,
        }])

        assert len(llm_requests) == 1, "Should have created one LLM request"
        assert llm_requests[0].llm_request_id is not None
        assert llm_requests[0].model == fb.LLMModels.GEMINI_2_5_FLASH_LITE
        assert llm_requests[0].requested_at_utc is None, "Request should not be executed yet"

        await db.close()

    @pytest.mark.asyncio
    async def test_llm_db_add_llm_requests_with_schema(self):
        """Test that WMSnapshotContentLLMExtractionDB can add LLM requests with response_schema."""
        import json

        db = WMSnapshotContentLLMExtractionDB(URLVersions.UNIS_1_TEST)
        await db.make_async(replace=True)

        llm_requests = await db._add_llm_requests([{
            "model": fb.LLMModels.GEMINI_2_5_FLASH_LITE,
            "system_prompt": "Extract cluster specifications.",
            "user_prompt": "Extract cluster name, CPUs, GPUs, and storage.",
            "temperature": 0.1,
            "response_schema": WMExtractedClusterSpecs,
        }])

        assert len(llm_requests) == 1, "Should have created one LLM request"
        assert llm_requests[0].response_schema is not None, "Should have response_schema"
        assert llm_requests[0].requested_at_utc is None, "Request should not be executed yet"

        schema = json.loads(llm_requests[0].response_schema)
        assert "properties" in schema, "Schema should have properties"

        await db.close()


@pytest.mark.xdist_group(name="web_archive_db_dependent")
class TestClusterSpecs:
    """Tests for ClusterSpecs."""

    @pytest.mark.parametrize("fmt", [
        fb.TableFormat.PARQUET,
        fb.TableFormat.CSV,
        fb.TableFormat.TSV,
        fb.TableFormat.MD,
        fb.TableFormat.JSON,
    ])
    def test_table_creates_all_formats(self, wm_snapshot_content_db, fmt):
        """Test that ClusterSpecs creates all formats."""
        table = ClusterSpecs(URLVersions.UNIS_1_TEST)
        table.make(replace=True)
        table.convert(replace=True)

        format_path = table.path_to_format(fmt)
        assert format_path.exists(), f"{fmt.value} file should exist"

    def test_table_has_expected_schema(self, wm_snapshot_content_db):
        """Test that ClusterSpecs has expected schema fields."""
        table = ClusterSpecs(URLVersions.UNIS_1_TEST)

        schema_fields = [field.title for field in table.schema.model_fields.values()]
        assert "Organization" in schema_fields or "org" in [f.lower() for f in schema_fields], \
            "Schema should have organization field"
        assert "URL" in schema_fields or "url" in [f.lower() for f in schema_fields], \
            "Schema should have URL field"
        assert "Year" in schema_fields or "year" in [f.lower() for f in schema_fields], \
            "Schema should have year field"

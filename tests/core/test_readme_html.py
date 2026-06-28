"""Tests for deterministic ``<object_stem>.readme.html`` generation."""

from enum import Enum
from typing import (
    ClassVar,
    override,
)

import pyarrow as pa
import pydantic as pyd
import pytest

from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.table import Table


class _Version(Enum):
    MAIN = DataObjectVersion(id="main", name="Main", description="Main dataset")


class _Row(pyd.BaseModel):
    city: str = pyd.Field(
        title="City name",
        description="Human-readable city name.",
    )
    temp_c: float = pyd.Field(
        title="Air temperature",
        description="2 m air temperature.",
        json_schema_extra={"units": "degC"},
    )


class _ReadmeTable(Table):
    id: ClassVar[str] = "readme_test_table"
    description: ClassVar[str] = "Table fixture for README tests"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_Version.MAIN,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _Row

    @override
    def _make(self) -> None:
        self.save_arrow(pa.table({"city": ["LA"], "temp_c": [20.0]}))


class _NoUnitsRow(pyd.BaseModel):
    label: str = pyd.Field(title="Label", description="A label.")


class _NoUnitsTable(_ReadmeTable):
    id: ClassVar[str] = "readme_test_no_units"
    row_schema: ClassVar[type[pyd.BaseModel]] = _NoUnitsRow

    @override
    def _make(self) -> None:
        self.save_arrow(pa.table({"label": ["x"]}))


@pytest.mark.usefixtures("test_local_data")
class TestReadmeHtml:
    def test_written_on_make(self):
        obj = _ReadmeTable(_Version.MAIN)
        obj.make(replace=True)
        assert obj.path_to_readme.exists()
        assert obj.path_to_readme.name == "readme_test_table-main.readme.html"

    def test_plain_html5_no_js(self):
        html = _ReadmeTable(_Version.MAIN).readme_html()
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert "<script" not in html.lower()
        assert "javascript:" not in html.lower()

    def test_data_dictionary_fields(self):
        html = _ReadmeTable(_Version.MAIN).readme_html()
        assert "Data dictionary" in html
        for token in (
            "city",
            "City name",
            "Human-readable city name.",
            "temp_c",
            "Air temperature",
            "2 m air temperature.",
        ):
            assert token in html

    def test_units_column_present_when_applicable(self):
        html = _ReadmeTable(_Version.MAIN).readme_html()
        assert "<th>Units</th>" in html
        assert "degC" in html

    def test_units_column_absent_when_not_applicable(self):
        html = _NoUnitsTable(_Version.MAIN).readme_html()
        assert "Data dictionary" in html
        assert "<th>Units</th>" not in html

    def test_header_metadata(self):
        html = _ReadmeTable(_Version.MAIN).readme_html()
        for token in (
            "readme_test_table",
            "Table fixture for README tests",
            "Main dataset",
        ):
            assert token in html

    def test_no_technical_details_in_header(self):
        html = _ReadmeTable(_Version.MAIN).readme_html()
        for token in ("Type", "Master format", "_ReadmeTable", "parquet"):
            assert token not in html

    def test_deterministic(self):
        obj = _ReadmeTable(_Version.MAIN)
        assert obj.readme_html() == obj.readme_html()

    def test_kind_is_table(self):
        assert _ReadmeTable.readme_kind == "table"

"""Tests for deterministic ``<object_stem>.schema.json`` generation."""

import json
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


class _SchemaTable(Table):
    id: ClassVar[str] = "schema_test_table"
    description: ClassVar[str] = "Table fixture for schema tests"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_Version.MAIN,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _Row

    @override
    def _make(self) -> None:
        self.save_arrow(pa.table({"city": ["LA"], "temp_c": [20.0]}))


@pytest.mark.usefixtures("test_local_data")
class TestSchemaJson:
    def test_written_on_make(self):
        obj = _SchemaTable(_Version.MAIN)
        obj.make(replace=True)
        assert obj.path_to_schema.exists()
        assert obj.path_to_schema.name == "schema_test_table-main.schema.json"

    def test_valid_json_schema_document(self):
        schema = json.loads(_SchemaTable(_Version.MAIN).row_schema_json())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {"city", "temp_c"}
        assert schema["required"] == ["city", "temp_c"]

    def test_field_metadata_carried_through(self):
        schema = json.loads(_SchemaTable(_Version.MAIN).row_schema_json())
        city = schema["properties"]["city"]
        assert city["type"] == "string"
        assert city["title"] == "City name"
        assert city["description"] == "Human-readable city name."
        temp = schema["properties"]["temp_c"]
        assert temp["type"] == "number"
        assert temp["units"] == "degC"

    def test_matches_pydantic_schema(self):
        schema = json.loads(_SchemaTable(_Version.MAIN).row_schema_json())
        del schema["$schema"]
        assert schema == _Row.model_json_schema()

    def test_trailing_newline_and_indent(self):
        out = _SchemaTable(_Version.MAIN).row_schema_json()
        assert out.endswith("}\n")
        assert "\n  " in out

    def test_deterministic(self):
        obj = _SchemaTable(_Version.MAIN)
        assert obj.row_schema_json() == obj.row_schema_json()

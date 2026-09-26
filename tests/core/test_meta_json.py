"""Tests for the consumer-facing ``<object_stem>.meta.json`` provenance record."""

import json
import re
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import pyarrow as pa
import pydantic as pyd
import pytest

from p40_flowbase.core.base import (
    DataObject,
    DataObjectVersion,
)
from p40_flowbase.core.formats import FigureFormat
from p40_flowbase.core.table import Table


class _Version(Enum):
    MAIN = DataObjectVersion(id="main", name="Main", description="Main dataset")


class _UpstreamRow(pyd.BaseModel):
    x: int = pyd.Field(title="X", description="An x.")


class _Upstream(Table):
    id: ClassVar[str] = "meta_upstream"
    description: ClassVar[str] = "Upstream fixture"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_Version.MAIN,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _UpstreamRow

    @override
    def _make(self) -> None:
        self.save_arrow(pa.table({"x": [1]}))


class _Row(pyd.BaseModel):
    city: str = pyd.Field(title="City name", description="Human-readable city name.")
    temp_c: float = pyd.Field(title="Air temperature", description="2 m air temperature.")


class _MetaTable(Table):
    id: ClassVar[str] = "meta_test_table"
    description: ClassVar[str] = "Table fixture for meta tests"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_Version.MAIN,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _Row
    asset_deps: ClassVar[tuple[type[DataObject], ...]] = (_Upstream,)

    @override
    def _make(self) -> None:
        self.save_arrow(pa.table({"city": ["LA"], "temp_c": [20.0]}))


class _Blob(DataObject):
    """Non-Table object: no ``_make_summary`` fields, no schema pointer."""

    id: ClassVar[str] = "meta_blob"
    description: ClassVar[str] = "Non-table fixture"
    make_format: ClassVar[FigureFormat] = FigureFormat.PNG  # pyright: ignore[reportIncompatibleVariableOverride]
    supported_versions: ClassVar[tuple[Enum, ...]] = (_Version.MAIN,)

    @override
    def _make(self) -> None:
        self.path_to_format(self.make_format).write_bytes(b"\x89PNG blob")


class _LinkedVersion(Enum):
    Q3 = DataObjectVersion(
        id="q3", name="Q3", description="Third quarter", links=("inbox/260926_sp_bank",)
    )


class _Linked(Table):
    id: ClassVar[str] = "meta_linked_table"
    description: ClassVar[str] = "Linked fixture"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_LinkedVersion.Q3,)
    row_schema: ClassVar[type[pyd.BaseModel]] = _UpstreamRow
    links: ClassVar[tuple[str, ...]] = (
        "projects/sp", "users/anton", "inbox/260926_sp_bank",
    )

    @override
    def _make(self) -> None:
        self.save_arrow(pa.table({"x": [1]}))


def _meta(obj: DataObject) -> dict[str, Any]:
    obj.make(replace=True)
    return json.loads(obj.path_to_meta.read_text())


@pytest.mark.usefixtures("test_local_data")
class TestMetaJson:
    def test_written_on_make(self):
        obj = _MetaTable(_Version.MAIN)
        obj.make(replace=True)
        assert obj.path_to_meta.exists()
        assert obj.path_to_meta.name == "meta_test_table-main.meta.json"

    def test_identity_and_version(self):
        meta = _meta(_MetaTable(_Version.MAIN))
        assert meta["object_id"] == "meta_test_table"
        assert meta["object_stem"] == "meta_test_table-main"
        assert meta["master_format"] == "parquet"
        assert meta["version"] == {
            "id": "main", "name": "Main", "description": "Main dataset",
        }

    def test_made_at_utc_iso_z(self):
        meta = _meta(_MetaTable(_Version.MAIN))
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", meta["made_at_utc"]
        )

    def test_producer(self):
        meta = _meta(_MetaTable(_Version.MAIN))
        producer = meta["producer"]
        # Package is the top-level module of the object's class.
        assert producer["package"] == "tests"
        # Version is None when that package is not an installed distribution.
        assert producer["version"] is None
        assert producer["class"].endswith("._MetaTable")

    def test_content_is_uniform(self):
        meta = _meta(_MetaTable(_Version.MAIN))
        content = meta["content"]
        # content stays uniform across all object classes: bytes + sha256 only.
        assert set(content) == {"bytes", "sha256"}
        assert content["bytes"] > 0
        assert re.fullmatch(r"[0-9a-f]{64}", content["sha256"])

    def test_class_specific_fields_under_optional(self):
        opt = _meta(_MetaTable(_Version.MAIN))["optional"]
        assert opt["rows"] == 1
        assert opt["cols"] == 2
        assert opt["schema"] == "meta_test_table-main.schema.json"

    def test_root_fields_uniform_no_class_specifics(self):
        meta = _meta(_MetaTable(_Version.MAIN))
        assert set(meta) == {
            "object_id", "object_stem", "description", "version",
            "master_format", "producer", "lineage", "links", "made_at_utc",
            "content", "optional",
        }

    def test_links_default_empty(self):
        assert _meta(_MetaTable(_Version.MAIN))["links"] == []

    def test_links_class_then_version_deduplicated(self):
        assert _meta(_Linked(_LinkedVersion.Q3))["links"] == [
            "projects/sp", "users/anton", "inbox/260926_sp_bank",
        ]

    def test_malformed_class_link_rejected_at_definition(self):
        with pytest.raises(ValueError, match="not a p40"):

            class _Bad(_Blob):  # pyright: ignore[reportUnusedClass]
                links: ClassVar[tuple[str, ...]] = ("Projects/SP",)

    def test_malformed_version_link_rejected(self):
        with pytest.raises(ValueError, match="not a p40"):
            DataObjectVersion(id="x", name="x", description="x", links=("nope",))

    def test_non_table_has_same_root_and_empty_optional(self):
        meta = _meta(_Blob(_Version.MAIN))
        # Same uniform root as a Table; class-specific bucket is empty (not absent).
        assert set(meta) == {
            "object_id", "object_stem", "description", "version",
            "master_format", "producer", "lineage", "links", "made_at_utc",
            "content", "optional",
        }
        assert set(meta["content"]) == {"bytes", "sha256"}
        assert meta["optional"] == {}

    def test_lineage_direct_dep_ids(self):
        meta = _meta(_MetaTable(_Version.MAIN))
        assert meta["lineage"]["deps"] == ["meta_upstream"]

    def test_hash_reflects_content_change(self):
        obj = _MetaTable(_Version.MAIN)
        h1 = _meta(obj)["content"]["sha256"]

        class _Other(_MetaTable):
            @override
            def _make(self) -> None:
                self.save_arrow(pa.table({"city": ["NY"], "temp_c": [9.0]}))

        h2 = _meta(_Other(_Version.MAIN))["content"]["sha256"]
        assert h1 != h2

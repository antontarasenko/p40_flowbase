"""Per-object log file behaviour for ``DataObject.make()`` /
``convert()`` / ``delete()``.

Covers:

- The per-object FileHandler is attached only during the lifecycle call
  and writes to ``<local_dir>/<object_stem>.log`` in append mode.
- Subclass ``_make_summary`` fields land in the ``make_summary`` line.
- Concurrent ``make()`` calls (via ``asyncio.gather`` of
  ``asyncio.to_thread``) produce two log files, each holding **only**
  its own object's records — verifies the ContextVar+Filter isolation.
- ``convert()`` appends a ``convert_summary`` line to the same file.
- ``delete()`` writes ``delete_summary`` then removes the local_dir
  (log file goes with it — intentional).
- Failures are captured via ``logger.exception(...)`` and re-raised.
"""

import asyncio
from enum import Enum
from typing import override

import pyarrow as pa
import pydantic as pyd
import pytest

from p40_flowbase.core.base import (
    DataObject,
    DataObjectVersion,
)
from p40_flowbase.core.composite import Composite
from p40_flowbase.core.formats import (
    CompositeFormat,
    TableFormat,
)
from p40_flowbase.core.table import Table


class _V(Enum):
    V1 = DataObjectVersion(id="logv1", name="v1", description="logging test")


class _Row(pyd.BaseModel):
    n: int
    name: str


class _LogTable(Table):
    id = "logging_table_a"
    description = "log test table A"
    supported_versions = (_V.V1,)
    row_schema = _Row

    @override
    def _make(self) -> None:
        self.save_arrow(
            pa.Table.from_pylist([
                {"n": 1, "name": "a"},
                {"n": 2, "name": "b"},
                {"n": 3, "name": "c"},
            ])
        )


class _LogTableB(Table):
    id = "logging_table_b"
    description = "log test table B"
    supported_versions = (_V.V1,)
    row_schema = _Row

    @override
    def _make(self) -> None:
        self.save_arrow(pa.Table.from_pylist([{"n": 9, "name": "z"}]))


class _FailingTable(Table):
    id = "logging_failing_table"
    description = "always fails"
    supported_versions = (_V.V1,)
    row_schema = _Row

    @override
    def _make(self) -> None:
        msg = "boom"
        raise RuntimeError(msg)


class _LogComposite(Composite):
    id = "logging_composite"
    description = "log test composite"
    supported_versions = (_V.V1,)

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)
        (files_dir / "alpha.txt").write_text("hello\n")
        (files_dir / "beta.txt").write_text("world\n")


# ---- helpers -----------------------------------------------------------


def _read_log(obj: DataObject) -> str:
    log_path = obj.local_dir / f"{obj.object_stem}.log"
    return log_path.read_text()


# ---- single-object summaries ------------------------------------------


def test_make_writes_per_object_log_with_summary(test_local_data):
    table = _LogTable(_V.V1)
    table.delete()
    table.make()

    log = _read_log(table)
    assert f"=== begin make | object={table.object_stem} ===" in log
    assert "make_summary | " in log
    assert " rows=3" in log
    assert " cols=2" in log
    assert " bytes=" in log
    assert " dur_s=" in log
    expected_path = str(table.path_to_format(TableFormat.PARQUET).resolve())
    assert f"path={expected_path}" in log
    assert f"=== end make | object={table.object_stem} ===" in log


def test_composite_make_summary_includes_file_count(test_local_data):
    comp = _LogComposite(_V.V1)
    comp.delete()
    comp.make()
    log = _read_log(comp)
    assert "make_summary | " in log
    assert " files=2 " in log
    assert " files_bytes=" in log


def test_convert_appends_summary_to_same_log(test_local_data):
    table = _LogTable(_V.V1)
    table.delete()
    table.make()
    table.convert(TableFormat.CSV)
    log = _read_log(table)
    assert "convert_summary | " in log
    assert " fmt=csv " in log
    expected_path = str(table.path_to_format(TableFormat.CSV).resolve())
    assert f"path={expected_path}" in log


def test_delete_logs_summary_then_removes_local_dir(test_local_data):
    table = _LogTable(_V.V1)
    table.delete()
    table.make()
    assert table.local_dir.exists()

    table.delete()
    # Local dir (and the log file inside it) is gone — by design.
    assert not table.local_dir.exists()


# ---- failure capture ---------------------------------------------------


def test_make_failure_logs_traceback_and_reraises(test_local_data):
    failing = _FailingTable(_V.V1)
    failing.delete()
    with pytest.raises(RuntimeError, match="boom"):
        failing.make()
    log = _read_log(failing)
    assert f"make_failed | object={failing.object_stem}" in log
    assert "Traceback" in log
    assert "RuntimeError: boom" in log


# ---- concurrency isolation --------------------------------------------


async def test_concurrent_make_isolates_per_object_logs(test_local_data):
    """ContextVar+Filter: two Tables built concurrently must not bleed
    into each other's log files."""
    a = _LogTable(_V.V1)
    b = _LogTableB(_V.V1)
    a.delete()
    b.delete()

    await asyncio.gather(
        asyncio.to_thread(a.make),
        asyncio.to_thread(b.make),
    )

    log_a = _read_log(a)
    log_b = _read_log(b)

    # Each log carries its own object stem
    assert a.object_stem in log_a
    assert b.object_stem in log_b
    # ...and not the other's
    assert b.object_stem not in log_a
    assert a.object_stem not in log_b



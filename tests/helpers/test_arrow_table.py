"""Tests for ``arrow_table``: pydantic rows, or dicts validated through the
model, as a pyarrow table under the model's schema."""

from __future__ import annotations

import pydantic as pyd
import pytest

from p40_flowbase.helpers import (
    arrow_schema_from_pydantic,
    arrow_table,
)


class _Row(pyd.BaseModel):
    city: str
    count_cnt: int
    note: str | None = None


class TestArrowTable:
    def test_models_and_dicts(self):
        table = arrow_table(
            [_Row(city="Budapest", count_cnt=2), {"city": "Wien", "count_cnt": 3}],
            _Row,
        )
        assert table.schema.equals(arrow_schema_from_pydantic(_Row))
        assert table.column("city").to_pylist() == ["Budapest", "Wien"]
        assert table.column("note").to_pylist() == [None, None]

    def test_a_bad_dict_is_refused(self):
        with pytest.raises(pyd.ValidationError):
            arrow_table([{"city": "Wien"}], _Row)

    def test_empty(self):
        assert arrow_table([], _Row).num_rows == 0

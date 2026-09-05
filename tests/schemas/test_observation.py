"""Tests for the ``p40_flowbase.schemas`` observation chain.

Covers the validators (green and red paths) and the five-backend
contract: NDJSON value validation, Arrow schema derivation, JSON schema
for LLM structured outputs, and ``table=True`` DB subclassing.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pydantic as pyd
import pytest
import sqlmodel as sm

from p40_flowbase import schemas as sc
from p40_flowbase.helpers import arrow_schema_from_pydantic

GOOD_OBSERVATION = {
    "ref_id": "nvda_revenue_q3_fy2026",
    "entity": "NVIDIA Corporation",
    "entity_id": "NVDA",
    "entity_id_system": "ticker",
    "metric": "revenue_gaap_b_usd",
    "period_start_date": "2025-07-28",
    "period_end_date": "2025-10-26",
    "source_url": "https://investor.nvidia.com/q3-fy2026-10q",
    "source_label": "NVIDIA Q3 FY2026 Form 10-Q",
    "quote": "Revenue was <b>$57.0 billion</b>, up 62% from a year ago.",
    "quote_display": "Revenue was $57.0 billion, up 62% from a year ago.",
    "value_float": 57.0,
}


def _good(**overrides: Any) -> dict[str, Any]:
    row = {**GOOD_OBSERVATION, **overrides}
    return {k: v for k, v in row.items() if v is not None}


class TestObservationValidators:
    def test_green_period_row(self):
        obs = sc.Observation.model_validate_json(json.dumps(_good()))
        assert obs.value == 57.0
        assert obs.period_end_date == dt.date(2025, 10, 26)

    def test_green_timeless_row(self):
        obs = sc.Observation.model_validate(
            _good(period_start_date=None, period_end_date=None, value_float=None,
                  value_str="AA+")
        )
        assert obs.value == "AA+"

    def test_red_two_values(self):
        with pytest.raises(pyd.ValidationError, match="exactly one"):
            sc.Observation.model_validate(_good(value_int=57))

    def test_red_no_value(self):
        with pytest.raises(pyd.ValidationError, match="exactly one"):
            sc.Observation.model_validate(_good(value_float=None))

    def test_red_as_of_and_period(self):
        with pytest.raises(pyd.ValidationError, match="not both"):
            sc.Observation.model_validate(_good(as_of_date="2025-10-26"))

    def test_red_half_period_pair(self):
        with pytest.raises(pyd.ValidationError, match="set together"):
            sc.Observation.model_validate(_good(period_end_date=None))

    def test_red_period_order(self):
        with pytest.raises(pyd.ValidationError, match="<="):
            sc.Observation.model_validate(
                _good(period_start_date="2025-10-27")
            )

    def test_red_extra_field(self):
        with pytest.raises(pyd.ValidationError, match="Extra inputs"):
            sc.Observation.model_validate(_good(quote_verified=True))

    def test_red_entity_id_without_system(self):
        with pytest.raises(pyd.ValidationError, match="set together"):
            sc.Observation.model_validate(_good(entity_id_system=None))

    def test_red_entity_id_system_vocabulary(self):
        with pytest.raises(pyd.ValidationError, match="pattern"):
            sc.Observation.model_validate(_good(entity_id_system="bloomberg"))

    def test_naive_utc_coercion(self):
        obs = sc.Observation.model_validate(
            _good(source_accessed_at_utc="2026-07-12T11:30:00+05:00")
        )
        assert obs.source_accessed_at_utc == dt.datetime(2026, 7, 12, 6, 30)
        assert obs.source_accessed_at_utc is not None
        assert obs.source_accessed_at_utc.tzinfo is None


class TestTypedLevels:
    def test_instant_requires_as_of(self):
        with pytest.raises(pyd.ValidationError, match="as_of_date"):
            sc.InstantObservation.model_validate(
                {"ref_id": "x", "metric": "m_cnt", "source_url": "https://e.com",
                 "quote": "q"}
            )

    def test_period_label(self):
        row = sc.PeriodObservation.model_validate(
            {"ref_id": "x", "metric": "m_cnt", "source_url": "https://e.com",
             "quote": "q", "period_start_date": "2025-07-28",
             "period_end_date": "2025-10-26", "period_label": "Q3 FY2026"}
        )
        assert row.period_label == "Q3 FY2026"

    def test_period_order_red(self):
        with pytest.raises(pyd.ValidationError, match="<="):
            sc.PeriodObservation.model_validate(
                {"ref_id": "x", "metric": "m_cnt", "source_url": "https://e.com",
                 "quote": "q", "period_start_date": "2025-10-27",
                 "period_end_date": "2025-10-26"}
            )

    def test_project_subclass_typed_value(self):
        class QuarterlyRevenue(sc.PeriodObservation):
            revenue_gaap_b_usd: float

        row = QuarterlyRevenue.model_validate(
            {"ref_id": "x", "metric": "revenue_gaap_b_usd",
             "source_url": "https://e.com", "quote": "q",
             "period_start_date": "2025-07-28", "period_end_date": "2025-10-26",
             "revenue_gaap_b_usd": 57.0}
        )
        assert row.revenue_gaap_b_usd == 57.0
        assert "revenue_gaap_b_usd" in arrow_schema_from_pydantic(QuarterlyRevenue).names


class TestBackends:
    def test_arrow_schemas_derive(self):
        for model in (sc.ReferenceBase, sc.MetricObservation,
                      sc.InstantObservation, sc.PeriodObservation,
                      sc.Observation):
            schema = arrow_schema_from_pydantic(model)
            assert "quote" in schema.names
        assert len(arrow_schema_from_pydantic(sc.Observation)) == 22

    def test_json_schema_llm_contract(self):
        js = sc.Observation.model_json_schema()
        assert js["additionalProperties"] is False
        assert set(js["required"]) == {"ref_id", "source_url", "quote", "metric"}

    def test_table_true_subclass(self):
        class SchTestObservationRow(sc.Observation, table=True):
            row_pk: int | None = sm.Field(default=None, primary_key=True)

        _ = SchTestObservationRow
        table = sm.SQLModel.metadata.tables["schtestobservationrow"]
        assert "quote" in table.columns
        assert "row_pk" in table.columns


class TestVerifyQuote:
    def test_exact(self):
        assert sc.verify_quote(quote="$57.0 billion", source_text="was $57.0 billion.") == "exact"

    def test_normalized_only(self):
        assert sc.verify_quote(
            quote="was  $57.0 billion", source_text="was $57.0 billion."
        ) == "normalized"

    def test_no_match(self):
        assert sc.verify_quote(quote="$58.0 billion", source_text="was $57.0 billion.") is None

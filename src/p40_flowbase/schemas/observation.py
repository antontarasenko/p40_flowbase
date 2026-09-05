"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import datetime as dt
import re
import unicodedata

import pydantic as pyd

from p40_flowbase.schemas.base import SchemaBase

REF_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
ENTITY_ID_SYSTEM_PATTERN = r"^(ticker|cik|lei|isin|figi)$"


def normalize_text(text: str) -> str:
    """Unicode NFKC, collapse each whitespace run to one space, strip ends."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def verify_quote(*, quote: str, source_text: str) -> str | None:
    """Diagnostic matcher used by ``ck.QuotesVerified`` failure messages.

    The verification contract is binary: only ``"exact"`` (byte-identical
    substring) verifies. ``"normalized"`` (matches after NFKC + whitespace
    collapse) is reported on failure as a hint that the quote came from a
    different rendering of the source and should be re-extracted from the
    stored artifact. ``None``: no match at all.
    """
    if quote in source_text:
        return "exact"
    if normalize_text(quote) in normalize_text(source_text):
        return "normalized"
    return None


class ReferenceBase(SchemaBase):
    """The evidence core of an extracted record: id, source, literal quote.

    A way to find, ground, and verify any piece of information: **find**
    via ``source_url`` (+ ``source_transcript`` for binary sources),
    **ground** via ``quote`` (byte-anchored to the stored verification
    artifact, optionally offset-pinned), **verify** via the producer
    stamp and the structural re-proof ``ck.QuotesVerified`` runs at
    ``make()``.

    Deliberately minimal so many record types can build on it without
    inheriting fields they do not need: no subject, no valid time, no
    value at this level. The shipped chain adds them stepwise:
    :class:`MetricObservation` (entity + metric),
    :class:`InstantObservation` / :class:`PeriodObservation` (valid
    time, required per class), :class:`Observation` (wide value ledger).
    Kept mixin-clean (no cross-field validators), so it also composes
    with other bases via multiple inheritance.
    """

    ref_id: str = pyd.Field(
        title="Reference id",
        description="Stable slug identifying this record within a dataset.",
        examples=["nvda_revenue_q3_fy2026"],
        pattern=REF_ID_PATTERN,
    )
    note: str | None = pyd.Field(
        default=None,
        title="Note",
        description="Free-text caveats and context; no evidential weight.",
    )
    source_url: str = pyd.Field(
        title="Source URL",
        description="URL of the source document the quote was taken from.",
        examples=["https://investor.nvidia.com/q3-fy2026-10q"],
    )
    source_label: str | None = pyd.Field(
        default=None,
        title="Source label",
        description="Human-readable source name.",
        examples=["NVIDIA Q3 FY2026 Form 10-Q"],
    )
    source_published_date: dt.date | None = pyd.Field(
        default=None,
        title="Source published date",
        description="Date the source itself was published.",
    )
    source_accessed_at_utc: dt.datetime | None = pyd.Field(
        default=None,
        title="Source accessed at (UTC)",
        description="When the source content was retrieved.",
    )
    source_transcript: str | None = pyd.Field(
        default=None,
        title="Source transcript",
        description=(
            "Reference to the stored text version of the source used as "
            "the verification artifact: the pinned canonical extraction "
            "of a PDF/binary (or an OCR'd scan, or an AV transcript), "
            "addressed as '<object_stem>.files/<relative_path>' or "
            "another locator the project resolver understands. None = "
            "the raw stored body of source_url is itself the "
            "verification artifact (HTML, text, JSON sources)."
        ),
        examples=["sec_filings-main.files/260712_nvda/10q.pdftotext.txt"],
    )
    quote: str = pyd.Field(
        title="Quote (literal)",
        description=(
            "Literal excerpt supporting the record: a byte-identical "
            "substring of the verification artifact - the transcript "
            "referenced by source_transcript when set, else the raw "
            "stored body of source_url (markup included). The ONLY "
            "verification input; re-proven at make() by "
            "ck.QuotesVerified."
        ),
        examples=["Revenue was <b>$57.0 billion</b>, up 62% from a year ago."],
    )
    quote_display: str | None = pyd.Field(
        default=None,
        title="Quote (display)",
        description=(
            "Human-readable rendering of the quote for reports and "
            "review (markup stripped, whitespace tidied). Presentation "
            "only, never verified, no evidential weight. None = quote "
            "is already readable as-is."
        ),
        examples=["Revenue was $57.0 billion, up 62% from a year ago."],
    )
    quote_offset_char: int | None = pyd.Field(
        default=None,
        title="Quote offset",
        description=(
            "Optional, 0-based character offset of the quote in the "
            "verification artifact: pins WHICH occurrence when the quote "
            "is not unique, and lets a reviewer pull surrounding "
            "context. The end is derived (offset + len(quote)), never "
            "stored. When set, verification also requires "
            "artifact[offset:offset+len(quote)] == quote."
        ),
        ge=0,
        json_schema_extra={"units": "char"},
    )
    quote_checked_at_utc: dt.datetime | None = pyd.Field(
        default=None,
        title="Quote checked at (UTC)",
        description=(
            "When byte-identity of the quote against the stored source "
            "was confirmed by the producer's verification call (normal "
            "flow: extraction and verification run back to back as "
            "independent calls). ck.QuotesVerified re-proves the claim "
            "at make() regardless; None = producer never verified."
        ),
    )


class MetricObservation(ReferenceBase):
    """Evidence core + subject: what is measured, and of whom.

    The right base for timeless facts (constants, properties, contract
    terms). Time-bound metrics subclass :class:`InstantObservation` or
    :class:`PeriodObservation` instead.

    Qualifier convention: accounting and adjustment qualifiers ride in
    the metric name next to the units (``revenue_gaap_b_usd``,
    ``gdp_real_sa_b_usd``, ``cpi_nsa_yoy_pct``); there are deliberately
    no dedicated basis columns at this level.
    """

    entity: str | None = pyd.Field(
        default=None,
        title="Entity",
        description=(
            "Subject the metric describes (company, place, product). "
            "None when the metric name already identifies the subject."
        ),
        examples=["NVIDIA Corporation", "United States"],
    )
    entity_id: str | None = pyd.Field(
        default=None,
        title="Entity id",
        description=(
            "Machine identifier of the entity in the system declared by "
            "entity_id_system; the join key that survives entity-name "
            "variations ('NVIDIA Corporation' vs 'NVIDIA Corp.')."
        ),
        examples=["NVDA", "0001045810"],
    )
    entity_id_system: str | None = pyd.Field(
        default=None,
        title="Entity id system",
        description="Identifier system entity_id belongs to.",
        pattern=ENTITY_ID_SYSTEM_PATTERN,
        examples=["ticker", "cik"],
    )
    metric: str = pyd.Field(
        title="Metric",
        description=(
            "What is measured; units and qualifiers ride in the name "
            "(_usd, _cnt, _pct; gaap/non_gaap, real/nominal, sa/nsa)."
        ),
        examples=["revenue_gaap_b_usd", "population_cnt", "cpi_nsa_yoy_pct"],
    )

    @pyd.model_validator(mode="after")
    def _validate_entity_id(self) -> "MetricObservation":
        if (self.entity_id is None) != (self.entity_id_system is None):
            raise ValueError("entity_id and entity_id_system must be set together")
        return self


class InstantObservation(MetricObservation):
    """A stock observation: the value is true at one date, required."""

    as_of_date: dt.date = pyd.Field(
        title="As-of date",
        description="The single date the value is true of the world (stock).",
        examples=["2025-10-26"],
    )


class PeriodObservation(MetricObservation):
    """A flow observation: the value is true over an interval, required."""

    period_start_date: dt.date = pyd.Field(
        title="Period start",
        description="Interval start, inclusive.",
        examples=["2025-07-28"],
    )
    period_end_date: dt.date = pyd.Field(
        title="Period end",
        description="Interval end, inclusive (sources phrase periods inclusively).",
        examples=["2025-10-26"],
    )
    period_label: str | None = pyd.Field(
        default=None,
        title="Period label",
        description=(
            "The source's own name for the period ('Q3 FY2026', "
            "'FY2025', '2026M05'). The date pair is the machine truth; "
            "the label preserves what the filing actually said."
        ),
        examples=["Q3 FY2026"],
    )

    @pyd.model_validator(mode="after")
    def _validate_period(self) -> "PeriodObservation":
        if self.period_start_date > self.period_end_date:
            raise ValueError("period_start_date must be <= period_end_date")
        return self


_VALUE_FIELDS = ("value_float", "value_int", "value_str", "value_bool")


class Observation(MetricObservation):
    """Wide observation for mixed ledgers, seeds, and LLM contracts.

    Carries the optional temporal trio (a mixed ledger holds stock,
    flow, and timeless rows side by side) and one nullable column per
    value type with exactly one set (FHIR ``Observation.value[x]``
    precedent). Homogeneous tables should subclass the typed levels
    (:class:`InstantObservation` / :class:`PeriodObservation`) and add
    one typed, unit-suffixed value column instead.
    """

    as_of_date: dt.date | None = pyd.Field(
        default=None,
        title="As-of date",
        description="Valid date for a stock row; exclusive with the period pair.",
    )
    period_start_date: dt.date | None = pyd.Field(
        default=None,
        title="Period start",
        description="Flow interval start, inclusive; set with period_end_date.",
    )
    period_end_date: dt.date | None = pyd.Field(
        default=None,
        title="Period end",
        description="Flow interval end, inclusive.",
    )
    value_float: float | None = pyd.Field(
        default=None,
        title="Float value",
        description="The value when the metric is a real number.",
        examples=[57.0],
    )
    value_int: int | None = pyd.Field(
        default=None,
        title="Integer value",
        description="The value when the metric is a count or integer.",
        examples=[331449281],
    )
    value_str: str | None = pyd.Field(
        default=None,
        title="String value",
        description="The value when the metric is categorical or textual.",
        examples=["AA+"],
    )
    value_bool: bool | None = pyd.Field(
        default=None,
        title="Boolean value",
        description="The value when the metric is a yes/no fact.",
        examples=[True],
    )

    @pyd.model_validator(mode="after")
    def _validate_temporal(self) -> "Observation":
        has_start = self.period_start_date is not None
        has_end = self.period_end_date is not None
        if has_start != has_end:
            raise ValueError(
                "period_start_date and period_end_date must be set together"
            )
        if self.as_of_date is not None and has_start:
            raise ValueError("set as_of_date or the period pair, not both")
        if has_start and self.period_start_date > self.period_end_date:  # type: ignore[operator]
            raise ValueError("period_start_date must be <= period_end_date")
        return self

    @pyd.model_validator(mode="after")
    def _validate_exactly_one_value(self) -> "Observation":
        set_names = [n for n in _VALUE_FIELDS if getattr(self, n) is not None]
        if len(set_names) != 1:
            raise ValueError(
                f"exactly one of {_VALUE_FIELDS} must be set, "
                f"got {set_names or 'none'}"
            )
        return self

    @property
    def value(self) -> float | int | str | bool:
        """The single set value, whichever column holds it."""
        for n in _VALUE_FIELDS:
            v = getattr(self, n)
            if v is not None:
                return v
        raise ValueError("no value_* field set")

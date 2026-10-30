"""Tests for ``p40_flowbase.helpers.quotes``: the producer side of quote
verification, folding and reslicing, the content-addressed store, and the
numbers and raw-HTML gates."""

from __future__ import annotations

from decimal import Decimal

from p40_flowbase.helpers import quotes

RSQUO = "\u2019"
EM_DASH = "\u2014"
EN_DASH = "\u2013"
NBSP = "\u00a0"
SOFT_HYPHEN = "\u00ad"
FI_LIGATURE = "\ufb01"
NNBSP = "\u202f"

ARTIFACT = (
    "Revenue was <b>$57.0 billion</b>, up 62% from a year ago.\n\n"
    f"The company{RSQUO}s guidance {EM_DASH} for Q4 {EM_DASH} is $65.0{NBSP}billion.\n"
    "Revenue was <b>$57.0 billion</b> in the prior release too."
)


class TestNormMap:
    def test_folds_quotes_dashes_case_and_whitespace(self):
        folded, offsets = quotes.norm_map(f"  The{NBSP}Company{RSQUO}s  {EM_DASH} Q4 ")
        assert folded == "the company's - q4"
        assert len(offsets) == len(folded)

    def test_offsets_point_back_into_the_source(self):
        text = f"A{SOFT_HYPHEN}{SOFT_HYPHEN}B  C"
        folded, offsets = quotes.norm_map(text)
        assert folded == "ab c"
        assert [text[i] for i in offsets] == ["A", "B", " ", "C"]

    def test_ligature_expands_to_one_source_index(self):
        folded, offsets = quotes.norm_map(f"{FI_LIGATURE}x")
        assert folded == "fix"
        assert offsets == [0, 0, 1]

    def test_fold_is_the_text_alone(self):
        assert quotes.fold(f"A {EN_DASH} B") == "a - b"


class TestResliceQuote:
    def test_different_rendering_yields_the_exact_slice(self):
        resliced = quotes.reslice_quote(
            quote="the company's guidance - for q4 - is $65.0 billion.",
            artifact=ARTIFACT,
        )
        assert resliced is not None
        assert resliced.quote == (
            f"The company{RSQUO}s guidance {EM_DASH} for Q4 {EM_DASH} is $65.0{NBSP}billion."
        )
        assert ARTIFACT[resliced.start : resliced.end] == resliced.quote
        assert resliced.occurrences == 1

    def test_counts_occurrences(self):
        resliced = quotes.reslice_quote(quote="revenue was", artifact=ARTIFACT)
        assert resliced is not None
        assert resliced.start == 0
        assert resliced.occurrences == 2

    def test_none_when_absent_or_empty(self):
        assert quotes.reslice_quote(quote="net income", artifact=ARTIFACT) is None
        assert quotes.reslice_quote(quote="  ", artifact=ARTIFACT) is None

    def test_folded_once_for_many_quotes(self):
        folded = quotes.FoldedText(ARTIFACT)
        assert folded.reslice("revenue was") == quotes.reslice_quote(
            quote="revenue was", artifact=ARTIFACT
        )
        assert quotes.reslice_quote(
            quote="guidance", artifact=folded
        ) == folded.reslice("guidance")
        assert folded.reslice("net income") is None


class TestArtifactStore:
    def test_round_trip_and_idempotent_put(self, tmp_path):
        store = quotes.ArtifactStore(tmp_path / "artifacts")
        digest = store.put(ARTIFACT)
        assert digest == quotes.sha256_of_text(ARTIFACT)
        assert store.put(ARTIFACT) == digest
        assert store.get(digest) == ARTIFACT
        assert sorted(p.name for p in (tmp_path / "artifacts").iterdir()) == [
            f"{digest}.txt"
        ]

    def test_bytes_kept_exactly(self, tmp_path):
        store = quotes.ArtifactStore(tmp_path)
        text = "line one\r\nline two\n\n  trailing  "
        assert store.get(store.put(text)) == text

    def test_missing_and_tampered_are_none(self, tmp_path):
        store = quotes.ArtifactStore(tmp_path)
        assert store.get("0" * 64) is None
        digest = store.put("original")
        store.path_of(digest).write_bytes(b"changed")
        assert store.get(digest) is None


class TestNumbers:
    def test_group_separators_removed(self):
        assert quotes.numbers_in("1,234 and 1 234 and 1.234") == {Decimal(1234)}

    def test_decimals_and_columns(self):
        assert quotes.numbers_in("57.0 billion, up 62%") == {
            Decimal("57.0"),
            Decimal(62),
        }
        assert quotes.numbers_in("2025 2026") == {Decimal(2025), Decimal(2026)}
        assert quotes.numbers_in("57,5 percent") == {Decimal("57.5")}
        assert quotes.numbers_in("1,234.5 and 1,2345") == {
            Decimal("1234.5"),
            Decimal("1.2345"),
        }
        assert quotes.numbers_in(f"1{NNBSP}234 people") == {Decimal(1234)}

    def test_a_year_before_a_count_stays_two_numbers(self):
        assert quotes.numbers_in("k 31. srpnu 2024 481 zam") == {
            Decimal(31),
            Decimal(2024),
            Decimal(481),
        }
        assert quotes.numbers_in("In 2024, 1,489 people") == {
            Decimal(2024),
            Decimal(1489),
        }
        assert quotes.numbers_in("1 651   572 454   194 163") == {
            Decimal(1651),
            Decimal(572454),
            Decimal(194163),
        }

    def test_value_in_quote(self):
        quote = "Revenue was $57.0 billion, up 62% from a year ago."
        assert quotes.value_in_quote(value_text="57 billion USD", quote=quote)
        assert quotes.value_in_quote(value_text="62 percent", quote=quote)
        assert not quotes.value_in_quote(value_text="58.0", quote=quote)
        assert quotes.value_in_quote(value_text="not available", quote=quote)


class TestHtmlGate:
    HTML = (
        "<html><head><style>p{color:red}</style><script>var x=1;</script></head>"
        "<body><h1>Results</h1><p>Revenue was <b>&#36;57.0 billion</b>, up 62&#37;"
        " from a year ago.</p><ul><li>Guidance: $65.0 billion</li></ul></body></html>"
    )

    def test_html_text_drops_scripts_and_decodes_entities(self):
        text = quotes.html_text(self.HTML)
        assert "var x" not in text
        assert "color" not in text
        assert "$57.0 billion" in text
        assert "62%" in text

    def test_markdown_plain(self):
        plain = quotes.markdown_plain(
            "## Results\n\n- Revenue was **[$57.0 billion](https://e.com)**, "
            "up 62\\% from a year ago."
        )
        assert plain == "Results\n\nRevenue was $57.0 billion, up 62% from a year ago."

    def test_markdown_plain_drops_a_link_tail(self):
        cut = "TIMISOARA, RO](https://careers.example.com/x?id=1) and"
        assert quotes.markdown_plain(cut) == "TIMISOARA, RO and"

    def test_quote_in_html_across_renderings(self):
        quote = "Revenue was **$57.0 billion**, up 62% from a year ago"
        assert quotes.quote_in_html(quote=quote, raw_html=self.HTML)
        assert not quotes.quote_in_html(quote="Revenue was $58", raw_html=self.HTML)
        assert not quotes.quote_in_html(quote="Results", raw_html=self.HTML)
        assert quotes.quote_in_html(quote="Results", raw_html=self.HTML, min_chars=4)

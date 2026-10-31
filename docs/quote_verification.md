# Quote verification

A record built on `schemas.ReferenceBase` carries a literal `quote` from a stored artifact, and `ck.QuotesVerified` re-proves at `make()` that the quote is a byte-identical slice of that artifact. The contract is binary: only the exact bytes verify. Everything that makes a candidate quote able to pass, or decides whether it deserves to, happens where rows are built, with the helpers in `p40_flowbase.helpers.quotes`.

## Identity and anchor

The artifact is identified by its content. A producer stores every artifact once in an `ArtifactStore`, a directory of `<sha256>.txt` files, and writes the digest into `artifact_sha256`. The check fetches by digest, so a moved or re-fetched file is missing, never silently different. `source_url` stays as provenance for the reader.

The quote is anchored by its offset. `reslice_quote` finds a quote from another rendering in the artifact and returns the exact slice with its start, so the producer writes `quote` and `quote_offset_char` together, and a quote at an offset is never ambiguous.

## Producer

```python
import pydantic as pyd
import p40_flowbase as fb
from p40_flowbase import checks as ck
from p40_flowbase import schemas as sc
from p40_flowbase.helpers import (
    arrow_table,
    quotes,
)


def artifacts(obj: fb.DataObject) -> quotes.ArtifactStore:
    pages = PagesFiles(obj.version)
    return quotes.ArtifactStore(pages.path_to_format(fb.CompositeFormat.FILES) / "artifacts")


class Fact(sc.MetricObservation):
    quote: str = pyd.Field(min_length=12)
    value_text: str

    @pyd.model_validator(mode="after")
    def _value_supported(self) -> "Fact":
        if not quotes.value_in_quote(value_text=self.value_text, quote=self.quote):
            raise ValueError("the quote does not state the value")
        return self


class FactsTable(fb.Table):
    row_schema = Fact
    checks = (ck.QuotesVerified(store=artifacts),)

    def _make(self) -> None:
        store = artifacts(self)
        rows = []
        for page in PagesFiles(self.version).pages():
            sha = store.put(page.markdown)
            folded = quotes.FoldedText(page.markdown)
            for candidate in extract(page=page):
                sliced = folded.reslice(candidate.quote)
                if sliced is None:
                    continue
                rows.append(
                    Fact(
                        ref_id=candidate.ref_id,
                        source_url=page.url,
                        artifact_sha256=sha,
                        quote=sliced.quote,
                        quote_offset_char=sliced.start,
                        metric=candidate.metric,
                        value_text=candidate.value_text,
                    )
                )
        self.save_arrow(arrow_table(rows, Fact))
```

Constraints on what a quote must be belong to the row schema: a minimum length as a pydantic constraint, the numbers gate as a validator with `value_in_quote`. A page stored twice, as markdown and as raw HTML, gets the raw-HTML gate as a producer step with `quote_in_html`. Both gates are heuristics and never the proof. Two measures differ by design: a length constraint on `quote` counts every character, while `quote_in_html`'s `min_chars` counts the letters and digits of the folded quote, spaces and punctuation excluded. `numbers_in` reads a group as one to three digits followed by groups of three, so a year before a count stays two numbers; a decimal with exactly three fraction digits still reads as grouped. `markdown_plain` also drops the tail a quote cut inside a link keeps, the `](url)` after the link text.

## Check and report

`ck.QuotesVerified(store=...)` resolves by digest: `store(obj)` returns an `ArtifactStore`, or any object with `get(sha256) -> str | None`, a project's own manifest over files it already keeps. `ck.QuotesVerified(resolver=...)` is the 0.8.2 path, reading `source_url` and `source_transcript`. On either path, text that does not hash to the `artifact_sha256` a row carries is `hash_mismatch`, a re-fetched or stale file, and fails the run whatever `on_missing` says; `on_missing` applies to rows with no artifact at all: `"fail"`, `"skip"`, or the fraction of rows that must verify.

`report(obj)` judges every row and raises nothing. Each `schemas.QuoteStatus` carries one of five statuses, `verified`, `artifact_missing`, `hash_mismatch`, `quote_not_found` with a `normalized` hint when the quote would match after folding, and `offset_mismatch`, plus `occurrences`, how often the quote appears in the artifact, a review signal. `run(obj)` is built on the report and raises on the first row not verified, naming the status.

```python
class QuoteStatusTable(fb.Table):
    row_schema = sc.QuoteStatus

    def _make(self) -> None:
        rows = ck.QuotesVerified(store=artifacts).report(FactsTable(self.version))
        self.save_arrow(arrow_table(rows, sc.QuoteStatus))
```

## Fields

A row with structured fields read from one span, a product card's name, price, and size, keeps that span as its `quote` and proves the fields against it with `ck.FieldsInQuote(fields=("price_text", "size_text"))`: each listed column's text must occur in the quote after folding. `QuotesVerified` proves the quote against the artifact, `FieldsInQuote` the fields against the quote, so together they prove the fields against the page, and the second check reads the table alone. A field is the text as the page shows it, `$3.99`, `9 oz`; a parsed value lives in another column, as `value_float` beside `value_text`. A price that belongs to the next card is not in this card's quote and fails at `make()`; a per-pound price inside the card passes, since it is in the evidence, and telling it from the pack price is the producer's parsing, never a proof. A search for the fields within a window after the name was weighed and rejected: in a dense grid the window reaches the next card and passes what it was meant to catch, where the declared span fails it by construction. `report(obj)` returns one `schemas.FieldStatus` per present field, `verified` or `field_missing`; a null or empty field is passed over.

```python
class Card(sc.MetricObservation):
    quote: str = pyd.Field(min_length=12)
    price_text: str
    size_text: str | None = None


class CardsTable(fb.Table):
    row_schema = Card
    checks = (
        ck.QuotesVerified(store=artifacts),
        ck.FieldsInQuote(fields=("price_text", "size_text")),
    )
```

## Excerpts

A grader reads the page around the quote, not the whole page. `quotes.excerpt(quote=row.quote, artifact=page, offset=row.quote_offset_char, before=600, after=1800)` returns the artifact around the quote, cut at its offset when the slice there is the quote, else at its first occurrence after folding, and `None` when the quote is not in the artifact. The offset is what makes a name repeated in a facet, a carousel, and three cards unambiguous, so a producer that stores `quote_offset_char` gets the right card without a search.

## Folding

`norm_map` folds a text to the form two renderings share and keeps a map back to the original: NFKC per character, dashes and quotes to ASCII, invisible characters dropped, casefold, whitespace runs to one space, ends stripped. `verify_quote` uses the same folding for its `normalized` hint, so the hint and `reslice_quote` agree on what a different rendering is. `normalize_text`, used for `quote_display`, is unchanged.

## In your project, not in the library

Requests the library answers with a pattern rather than a feature, each one project's practice until a second project uses it unchanged:

- Excluded rows. A filter that drops rows keeps them in a second `Table` of the same version, its row schema the kept table's plus `reason` and `rule_version`, its lineage naming the source; the funnel is `SELECT reason, count(*) FROM t GROUP BY reason` over it, and a wrongful-drop review reads it as any table. Two objects, no helper.
- Labeled cases for a rule-based classifier. A versioned TSV of inputs and expected outputs beside the version's resources, read by a parametrized pytest over the classifier function and run before `make` by the component's test target; a case that fails fails the suite, which is the gate wanted. A check running tests at make time would make the library a second test runner.
- Transcript attribution. Two optional columns on the row schema, the speaker and the segment, filled by an interval lookup over the project's own segment map at row build; the library proves the quote, the project says who said it.
- Finding a field by a window around an anchor. Store the span as the quote and prove the fields with `FieldsInQuote`; a window is a guess at the span, the quote is the span.

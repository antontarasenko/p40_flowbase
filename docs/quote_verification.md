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
from p40_flowbase.helpers import quotes


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
            for candidate in extract(page=page):
                sliced = quotes.reslice_quote(quote=candidate.quote, artifact=page.markdown)
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
        self.save_arrow(fb.arrow_table(rows, Fact))
```

Constraints on what a quote must be belong to the row schema: a minimum length as a pydantic constraint, the numbers gate as a validator with `value_in_quote`. A page stored twice, as markdown and as raw HTML, gets the raw-HTML gate as a producer step with `quote_in_html`. Both gates are heuristics and never the proof.

## Check and report

`ck.QuotesVerified(store=...)` resolves by digest; `ck.QuotesVerified(resolver=...)` is the 0.8.2 path, reading `source_url` and `source_transcript`, and fails a row whose resolved text does not hash to the `artifact_sha256` it carries. `on_missing` applies to rows without an artifact: `"fail"`, `"skip"`, or the fraction of rows that must verify.

`report(obj)` judges every row and raises nothing. Each `schemas.QuoteStatus` carries one of four statuses, `verified`, `artifact_missing`, `quote_not_found` with a `normalized` hint when the quote would match after folding, and `offset_mismatch`, plus `occurrences`, how often the quote appears in the artifact, a review signal. `run(obj)` is built on the report and raises on the first row not verified, naming the status.

```python
class QuoteStatusTable(fb.Table):
    row_schema = sc.QuoteStatus

    def _make(self) -> None:
        rows = ck.QuotesVerified(store=artifacts).report(FactsTable(self.version))
        self.save_arrow(fb.arrow_table(rows, sc.QuoteStatus))
```

## Folding

`norm_map` folds a text to the form two renderings share and keeps a map back to the original: NFKC per character, dashes and quotes to ASCII, invisible characters dropped, casefold, whitespace runs to one space, ends stripped. `verify_quote` uses the same folding for its `normalized` hint, so the hint and `reslice_quote` agree on what a different rendering is. `normalize_text`, used for `quote_display`, is unchanged.

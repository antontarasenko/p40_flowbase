# p40-weather

Worked example for the [`p40_flowbase`](../../) data-pipeline framework. A complete eight-stage pipeline against the free [Open-Meteo](https://open-meteo.com/) API:

```
HTTPDB → Composite → Table → summary Table → AgentDB
                                                → narrative Table
                                                    → Figure / Document
```

This is the **recommended downstream layout**. Copy the structure for your own `<your_project>_data` package on top of `p40_flowbase`.

## Layout

```
examples/p40_weather/
├── pyproject.toml
├── README.md
├── src/p40_weather/
│   ├── __init__.py
│   ├── definitions.py
│   ├── helpers/
│   │   ├── __init__.py
│   │   └── open_meteo.py
│   ├── objects/
│   │   ├── __init__.py
│   │   └── weather.py
│   └── resources/
│       ├── templates/
│       │   ├── tables/
│       │   │   └── weather_summary_table.sql.jinja
│       │   ├── documents/
│       │   │   └── weather_doc.md.jinja
│       │   └── prompts/
│       │       └── weather_city_narrative_agent_db.md.jinja
│       └── versions/
│           └── weather_versions/
│               ├── cities-main.tsv
│               └── cities-backfill_2025.tsv
└── tests/
    └── test_smoke.py
```

| Folder | Holds |
|---|---|
| `objects/` | `DataObject` subclasses + their version metadata + Pydantic row schemas + custom `Group`/`Extra` factory-built tables. |
| `helpers/` | Third-party API wrappers and other reusable utilities. |
| `resources/templates/{tables,documents,prompts}/` | Jinja templates auto-discovered by `<id>.{sql,md}.jinja` convention. |
| `resources/versions/<EnumName_snake_case>/` | Per-version ops data (`<kind>-<version_id>.tsv`). |
| `definitions.py` | Dagster `Definitions`, the executable wiring. |
| `tests/` | Smoke tests. |

## Install

```sh
cd examples/p40_weather
pip install -e .
```

This pulls `p40_flowbase`, `claude-agent-sdk` (the only agent SDK this example uses), `dagster-dg-cli`, and `dagster-webserver`. The framework leaves agent SDKs and the Dagster CLI as optional/dev-only, so each downstream project pins its own versions in `dependencies`.

## Run the pipeline

Materialize all assets via Dagster:

```sh
export LOCAL_DATA=/tmp/p40_weather_data         # default if unset
export ANTHROPIC_API_KEY=sk-ant-...             # (optional) for the AgentDB step

dg dev -m p40_weather.definitions               # web UI, click "Materialize all"
# ...or one-shot:
dg launch -m p40_weather.definitions --assets '*'
```

Run for the 16-day forecast version:

```sh
dg launch -m p40_weather.definitions \
    --assets '*' \
    --partition backfill_2025
```

Force re-creation of selected assets via the `replace` resource:

```sh
dg launch -m p40_weather.definitions \
    --assets 'weather_summary_table*' \
    --config-json '{"resources":{"replace":{"config":{"replace":true}}}}'
```

Materialize side formats (CSV, JSON, SVG, ...) per run via the `convert_formats` resource:

```sh
dg launch -m p40_weather.definitions \
    --assets '*' --partition main \
    --config-json '{"resources":{"convert_formats":{"config":{"formats":["tsv","svg"]}}}}'
```

For per-asset static defaults, set `convert_formats` on the `fb.asset(...)` call in `definitions.py`.

## Materialize an object-version without Dagster

Making sync objects (`Table`, `Composite`, `Figure`, `Document`):

```python
import p40_flowbase as fb
from p40_weather.objects import WeatherSummaryTable, WeatherVersions
fb.DataObject.set_local_data("/tmp/p40_weather")
WeatherSummaryTable(WeatherVersions.MAIN).make(replace=True)
```

Making async objects (`HTTPDB`, `LLMDB`, `AgentDB`, `TableFromDB`):

```python
import asyncio
import p40_flowbase as fb
from p40_weather.objects import WeatherCityNarrativeAgentDB, WeatherVersions
fb.DataObject.set_local_data("/tmp/p40_weather")
asyncio.run(WeatherCityNarrativeAgentDB(WeatherVersions.MAIN).make(replace=True))
```

When calling from a event loop (inside an async function, Jupyter await cell, Dagster asset), use `amake()`:

```python
await WeatherSummaryTable(WeatherVersions.MAIN).amake(replace=True)
await WeatherCityNarrativeAgentDB(WeatherVersions.MAIN).amake(replace=True)
```

Every object exposes the same `make()` / `convert()` / `delete()`.

Track progress with:

```sh
tail -f $LOCAL_DATA/weather_city_narrative_agent_db-main/weather_city_narrative_agent_db-main.meta.log
```

## Pipeline overview

| Class | Output | Notes |
|---|---|---|
| `WeatherVersionConfig(fb.Table)` | Two-column `(key, value)` parquet of the active `WeatherVersion`'s fields | Snapshot of version metadata at run time; auto-tracks new fields via `dataclasses.asdict`. |
| `WeatherInputCities(fb.Table)` | `(name, latitude, longitude)` parquet | Reads `resources/versions/weather_versions/cities-<id>.tsv`. Lifting the catalog out of `WeatherVersions` keeps the enum import-time pure. |
| `WeatherHTTPDB(fb.HTTPDB)` | SQLite of HTTP requests + custom `WeatherHTTPRequestGroup` (per-run audit) + `WeatherHTTPRequestExtra` (per-request city metadata) | One row per `(version, city)`; cities read from `WeatherInputCities(version).df` |
| `WeatherResponseFiles(fb.Composite)` | One `<city>.json` per successful response | City name read from the join `HTTPRequest JOIN WeatherHTTPRequestExtra`, no URL parsing |
| `WeatherHourlyTable(fb.Table)` | Flat parquet `(city, ts_utc, temp_c, precip_mm)` | Python `_make` parses the JSON arrays |
| `WeatherSummaryTable(fb.Table)` | Per-city min/mean/max temp + total precip | **`.sql.jinja` template** at `resources/templates/tables/weather_summary_table.sql.jinja` |
| `WeatherCityNarrativeAgentDB(fb.AgentDB)` | One LLM task per city; one-sentence narrative | **`.md.jinja` prompt template** at `resources/templates/prompts/weather_city_narrative_agent_db.md.jinja`; `Models.CLAUDE_SONNET_4_6`; custom `WeatherAgentTaskGroup` / `WeatherAgentTaskExtra` |
| `WeatherCityNarrativeTable(fb.TableFromDB)` | `(city, narrative, model_id, cost_usd)` parquet | Joined from `AgentTask JOIN WeatherAgentTaskExtra` |
| `WeatherFigure(fb.Figure)` | Bar chart of mean temps | matplotlib pickle |
| `WeatherDoc(fb.Document)` | Markdown with summary table + LLM narratives + embedded SVG | Auto-converts the figure to SVG before embedding |

Dagster DAG (from `definitions.py`):

```
version_config

cities → http_db → files → hourly → summary ─┬→ narrative_db → narrative ─┐
                                             └→ figure ──────────────────→ doc
```

`version_config` is a leaf (no deps); it just persists the version snapshot alongside the rest of the run.

## Post-make checks

Each subclass declares a tuple of `fb.Check` objects in a `checks` ClassVar; the framework runs them after `make()` succeeds and raises `fb.CheckFailedError` (turning the Dagster asset red) on the first failure. A 100%-failed `WeatherHTTPDB`, a 0-row `WeatherSummaryTable`, or an empty-files `WeatherResponseFiles` no longer slip through silently.

```python
from p40_flowbase import checks as ck

class WeatherSummaryTable(fb.Table):
    checks = (ck.MinRows(1), ck.NoNulls("city", "temp_mean_c"), ck.Unique("city"))

class WeatherHTTPDB(fb.HTTPDB):
    checks = (ck.MinRequests(1), ck.MaxFailureRate(frac=0.0))
```

Built-ins: `MinRows`, `NoNulls`, `Unique` for `Table`; `MinFiles`, `NoEmptyFiles`, `MinFileSize`, `SchemaMatches` for `Composite`; `MinRequests`, `MaxFailureRate` for `HTTPDB`/`LLMDB`/`AgentDB`. Each check logs `check_start` / `check_ok` / `check_failed | <name>` to the per-object `.meta.log`.

## Versions

Two versions are wired into `WeatherVersions`:

| Version | `id` | Cities | Forecast horizon |
|---|---|---|---|
| `WeatherVersions.MAIN` | `main` | 5 (LA, NYC, Tokyo, Berlin, Cape Town) | 1 day |
| `WeatherVersions.BACKFILL_2025` | `backfill_2025` | 5 (same set) | 16 days |

Both share the same city catalog today; the cities live in TSVs at `resources/versions/weather_versions/cities-<id>.tsv`. To diverge them, edit one TSV; no Python code changes.

To add a new version: append a `WeatherVersions.<NEW>` enum member with the version's `WeatherVersion(id="<x>", cities=_load_cities("<x>"), ...)`, drop a `cities-<x>.tsv` next to the others, and Dagster picks up the new partition on next reload.

## Schema metadata

Every Pydantic field on `HourlyRow`, `SummaryRow`, `NarrativeRow` carries `title` / `description` / `examples` / `json_schema_extra={"units": ...}`, so `model.model_json_schema()` yields a fully-annotated machine-readable schema:

```json
"temp_mean_c": {
  "description": "Arithmetic mean of hourly air temperatures.",
  "examples": [7.4, 22.1],
  "title": "Mean temperature",
  "type": "number",
  "units": "degC"
}
```

The framework uses the schema *types* for the strict Arrow-vs-Pydantic schema check that runs before every parquet write (`fb.validate_arrow_against_pydantic`). The extra metadata is for downstream tooling (doc generators, column dictionaries, unit checkers).

## Tests

```sh
PYTHONPATH=src pytest tests/
```

The smoke tests mock the network at two seams:

- `fb.HTTPDB._execute_http_request`: returns canned Open-Meteo JSON for the 5 cities x 3 hours.
- `fb.AgentDB._execute_anthropic_agent`: returns a deterministic `"Mock narrative for task <uuid>."` with `total_cost_usd=0.0001`.

That covers the whole pipeline end-to-end without API keys or network.

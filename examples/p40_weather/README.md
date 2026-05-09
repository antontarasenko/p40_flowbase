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

Set the data root and an Anthropic API key, then materialize all assets via Dagster. `WeatherSettings` (in `src/p40_weather/config.py`) reads env vars without a prefix, so `LOCAL_DATA` and `ANTHROPIC_API_KEY` are picked up directly:

```sh
export LOCAL_DATA=/tmp/p40_weather_data         # default if unset
export ANTHROPIC_API_KEY=sk-ant-...             # for the AgentDB step

dg dev -m p40_weather.definitions                  # web UI, click "Materialize all"
# …or one-shot:
dg launch -m p40_weather.definitions --select '*'
```

Run for the 16-day forecast version:

```sh
dg launch -m p40_weather.definitions \
    --select '*' \
    --partition backfill_2025
```

Force re-creation of selected assets via the `replace` resource:

```sh
dg launch -m p40_weather.definitions \
    --select 'weather_summary_table+' \
    --config-json '{"resources":{"replace":{"config":{"replace":true}}}}'
```

The pipeline ends with `weather_doc-main.md` (or `weather_doc-backfill_2025.md`) containing the per-city summary table, the LLM-written narratives, and an embedded SVG bar chart of mean temperatures.

## Pipeline overview

| # | Class | Output | Notes |
|---|---|---|---|
| 1 | `WeatherHTTPDB(fb.HTTPDB)` | SQLite of HTTP requests + custom `WeatherHTTPRequestGroup` (per-run audit) + `WeatherHTTPRequestExtra` (per-request city metadata) | One row per `(version, city)` |
| 2 | `WeatherResponseFiles(fb.Composite)` | One `<city>.json` per successful response | City name read from the join `HTTPRequest ⨝ WeatherHTTPRequestExtra`, no URL parsing |
| 3 | `WeatherHourlyTable(fb.Table)` | Flat parquet `(city, ts_utc, temp_c, precip_mm)` | Python `_make` parses the JSON arrays |
| 4 | `WeatherSummaryTable(fb.Table)` | Per-city min/mean/max temp + total precip | **`.sql.jinja` template** at `resources/templates/tables/weather_summary_table.sql.jinja` |
| 5 | `WeatherCityNarrativeAgentDB(fb.AgentDB)` | One LLM task per city; one-sentence narrative | **`.md.jinja` prompt template** at `resources/templates/prompts/weather_city_narrative_agent_db.md.jinja`; `Models.CLAUDE_SONNET_4_6`; custom `WeatherAgentTaskGroup` / `WeatherAgentTaskExtra` |
| 6 | `WeatherCityNarrativeTable(fb.TableFromDB)` | `(city, narrative, model_id, cost_usd)` parquet | Joined from `AgentTask ⨝ WeatherAgentTaskExtra` |
| 7 | `WeatherFigure(fb.Figure)` | Bar chart of mean temps | matplotlib pickle |
| 8 | `WeatherDoc(fb.Document)` | Markdown with summary table + LLM narratives + embedded SVG | Auto-converts the figure to SVG before embedding |

Dagster DAG (from `definitions.py`):

```
http_db → files → hourly → summary ─┬→ narrative_db → narrative ─┐
                                    └→ figure ──────────────────→ doc
```

## Versions

Two versions are wired into `WeatherVersions`:

| Version | `id` | Cities | Forecast horizon |
|---|---|---|---|
| `WeatherVersions.MAIN` | `main` | 5 (LA, NYC, Tokyo, Berlin, Cape Town) | 1 day |
| `WeatherVersions.BACKFILL_2025` | `backfill_2025` | 5 (same set) | 16 days |

Both share the same city catalog today; the cities live in TSVs at `resources/versions/weather_versions/cities-<id>.tsv`. To diverge them, edit one TSV; no Python code changes.

To add a new version: append a `WeatherVersions.<NEW>` enum member with the version's `WeatherVersion(id="<x>", cities=_load_cities("<x>"), …)`, drop a `cities-<x>.tsv` next to the others, and Dagster picks up the new partition on next reload.

## Schema metadata

Every Pydantic field on `HourlyRow`, `SummaryRow`, `NarrativeRow` carries `title` / `description` / `examples` / `json_schema_extra={"units": …}`, so `model.model_json_schema()` yields a fully-annotated machine-readable schema:

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

- `fb.HTTPDB._execute_http_request`: returns canned Open-Meteo JSON for the 5 cities × 3 hours.
- `fb.AgentDB._execute_anthropic_agent`: returns a deterministic `"Mock narrative for task <uuid>."` with `total_cost_usd=0.0001`.

That covers the whole pipeline end-to-end without API keys or network.

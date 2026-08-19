"""Smoke test for p40_weather: imports and end-to-end build with mocked HTTP."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import p40_flowbase as fb
import pyarrow.compute as pc
import pytest
import sqlmodel as sm


@pytest.fixture
def local_data(tmp_path: Path) -> Path:
    """Point the framework's data root at a fresh temp dir; return that path."""
    fb.DataObject.set_local_data(str(tmp_path))
    return tmp_path


def _canned_response(latitude: float, longitude: float) -> str:
    return json.dumps(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": {
                "time": [
                    "2026-01-01T00:00",
                    "2026-01-01T01:00",
                    "2026-01-01T02:00",
                ],
                "temperature_2m": [5.0, 6.5, 7.0],
                "precipitation": [0.0, 0.1, 0.0],
            },
        }
    )


def test_imports() -> None:
    """Every public symbol importable."""
    from p40_weather.definitions import defs
    from p40_weather.helpers import build_forecast_url
    from p40_weather.objects import (
        ManualContextFiles,
        WeatherReportDoc,
        OpenMeteoCityTempMeanFigure,
        OpenMeteoCityHourlyTable,
        OpenMeteoForecastHTTPDB,
        ManualInputCitiesTable,
        OpenMeteoForecastResponseFiles,
        OpenMeteoCitySummaryTable,
        WeatherVersions,
    )

    assert defs is not None
    assert WeatherVersions.MAIN.value.forecast_days == 1
    assert WeatherVersions.BACKFILL_2025.value.forecast_days == 16
    assert build_forecast_url(latitude=0.0, longitude=0.0).startswith(
        "https://api.open-meteo.com/v1/forecast?"
    )
    assert ManualContextFiles.id == "manual_context_files"
    assert ManualInputCitiesTable.id == "manual_input_cities_table"
    from p40_weather.objects import PipelineVersionConfigTable
    assert PipelineVersionConfigTable.id == "pipeline_version_config_table"
    assert OpenMeteoForecastHTTPDB.id == "open_meteo_forecast_http_db"
    assert OpenMeteoForecastResponseFiles.id == "open_meteo_forecast_response_files"
    assert OpenMeteoCityHourlyTable.id == "open_meteo_city_hourly_table"
    assert OpenMeteoCitySummaryTable.id == "open_meteo_city_summary_table"
    assert OpenMeteoCityTempMeanFigure.id == "open_meteo_city_temp_mean_figure"
    assert WeatherReportDoc.id == "weather_report_doc"


def test_context_files_manual_composite(local_data: Path) -> None:
    """``ManualContextFiles`` materializes empty and is protected."""
    from p40_weather.objects import (
        ManualContextFiles,
        WeatherVersions,
    )

    obj = ManualContextFiles(WeatherVersions.MAIN)
    obj.make()

    # Populated out-of-band, so make() succeeds on an empty directory.
    files_dir = obj.path_to_format(fb.CompositeFormat.FILES)
    assert files_dir.is_dir()
    assert not any(files_dir.iterdir())

    # A dated entry uploaded by hand survives make(replace=True): replace
    # is neutralized and make never wipes the directory.
    entry = files_dir / "260614_project_description"
    entry.mkdir()
    (entry / "overview.md").write_text("project description")
    obj.make(replace=True)
    assert (entry / "overview.md").read_text() == "project description"

    # convert is a no-op: .files stays the only format.
    obj.convert(fb.CompositeFormat.ZIP)
    assert not obj.path_to_format(fb.CompositeFormat.ZIP).exists()

    # delete refuses.
    with pytest.raises(RuntimeError, match="Refusing to delete"):
        obj.delete()


def test_end_to_end_with_mocked_http(local_data: Path) -> None:
    """Run the full pipeline against canned Open-Meteo responses."""
    from p40_weather.objects import (
        AnthropicCityNarrativeAgentDB,
        AnthropicCityNarrativeTable,
        WeatherReportDoc,
        OpenMeteoCityTempMeanFigure,
        OpenMeteoCityHourlyTable,
        OpenMeteoForecastHTTPDB,
        ManualInputCitiesTable,
        OpenMeteoForecastResponseFiles,
        OpenMeteoCitySummaryTable,
        WeatherVersions,
    )

    # Materialize the cities catalog first; downstream stages read from it.
    cities_obj = ManualInputCitiesTable(WeatherVersions.MAIN)
    cities_obj.make(replace=True)
    cities_arrow = cities_obj.sql().to_arrow_table()
    assert cities_arrow.num_rows == 5
    assert sorted(cities_arrow.column_names) == [
        "latitude_deg",
        "longitude_deg",
        "name",
    ]

    canned: dict[tuple[float, float], str] = {
        (row["latitude_deg"], row["longitude_deg"]): _canned_response(
            row["latitude_deg"], row["longitude_deg"],
        )
        for row in cities_arrow.to_pylist()
    }

    async def fake_execute_http_request(
        self,
        http_client: Any,
        request_method: str,
        request_url: str,
        request_headers: str | None,
        request_body: str | None,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        from datetime import (
            UTC,
            datetime,
        )
        from urllib.parse import (
            parse_qs,
            urlparse,
        )

        del http_client, request_method, request_headers, request_body, ephemeral_headers
        qs = parse_qs(urlparse(request_url).query)
        lat = float(qs["latitude"][0])
        lon = float(qs["longitude"][0])
        body = canned[(lat, lon)]
        return {
            "response_status": 200,
            "response_headers": "{}",
            "response_body_text": body,
            "response_size": len(body),
            "latency": 0.001,
            "requested_at_utc": datetime.now(UTC),
        }

    with patch.object(
        fb.HTTPDB,
        "_execute_http_request",
        new=fake_execute_http_request,
    ):
        import asyncio

        async def _run() -> None:
            db = OpenMeteoForecastHTTPDB(WeatherVersions.MAIN)
            await db.make(replace=True)
            await db.close()

        asyncio.run(_run())

    # Audit: OpenMeteoHTTPRequestGroup carries the version metadata.
    from p40_weather.objects import (
        OpenMeteoHTTPRequestExtra,
        OpenMeteoHTTPRequestGroup,
    )

    async def _check_extras() -> None:
        db = OpenMeteoForecastHTTPDB(WeatherVersions.MAIN)
        try:
            async with db.session_factory() as session:
                groups = (
                    await session.exec(sm.select(OpenMeteoHTTPRequestGroup))
                ).all()
                extras = (
                    await session.exec(sm.select(OpenMeteoHTTPRequestExtra))
                ).all()
            assert len(groups) == 1
            g = groups[0]
            assert g.version_id == "main"  # type: ignore[attr-defined]
            assert g.forecast_days == 1  # type: ignore[attr-defined]
            assert g.cities_count == 5  # type: ignore[attr-defined]
            assert len(extras) == 5
            assert sorted(e.city_name for e in extras) == [  # type: ignore[attr-defined]
                "Berlin",
                "Cape Town",
                "Los Angeles",
                "New York",
                "Tokyo",
            ]
        finally:
            await db.close()

    asyncio.run(_check_extras())

    files_obj = OpenMeteoForecastResponseFiles(WeatherVersions.MAIN)
    files_obj.make(replace=True)

    files_dir = files_obj.path_to_format(fb.CompositeFormat.FILES)
    assert len(list(files_dir.glob("*.json"))) == 5

    hourly = OpenMeteoCityHourlyTable(WeatherVersions.MAIN)
    hourly.make(replace=True)
    hourly_arrow = hourly.sql().to_arrow_table()
    assert hourly_arrow.num_rows == 15  # 5 cities x 3 hours
    assert sorted(hourly_arrow.column_names) == [
        "city",
        "precip_mm",
        "temp_c",
        "ts_utc",
    ]

    summary = OpenMeteoCitySummaryTable(WeatherVersions.MAIN)
    summary.make(replace=True)
    summary_arrow = summary.sql().to_arrow_table()
    assert summary_arrow.num_rows == 5
    assert sorted(summary_arrow.column_names) == [
        "city",
        "precip_total_mm",
        "temp_max_c",
        "temp_mean_c",
        "temp_min_c",
    ]

    ############################################################################
    # AgentDB step: mock the Anthropic SDK call
    ############################################################################
    from datetime import (
        UTC,
        datetime,
    )

    async def _fake_anthropic(self, task: fb.AgentTask) -> fb.AgentTask:
        del self
        from p40_weather.objects import AnthropicCityNarrativeAgentDB
        now = datetime.now(UTC)
        async with AnthropicCityNarrativeAgentDB(
            WeatherVersions.MAIN
        ).session_factory() as session:
            task.started_at_utc = now
            task.final_response = (
                f"Mock narrative for task {task.agent_task_id}."
            )
            task.completed_at_utc = now
            task.num_turns = 1
            task.duration_ms = 1
            task.total_cost_usd = 0.0001
            task.is_error = False
            session.add(task)
            await session.commit()
            await session.refresh(task)
        return task

    with patch.object(
        fb.AgentDB, "_execute_anthropic_agent", new=_fake_anthropic,
    ):
        async def _run_agent() -> None:
            db = AnthropicCityNarrativeAgentDB(WeatherVersions.MAIN)
            await db.make(replace=True)
            await db.close()

        asyncio.run(_run_agent())

    narrative_table = AnthropicCityNarrativeTable(WeatherVersions.MAIN)
    narrative_table.make(replace=True)
    narrative_arrow = narrative_table.sql().to_arrow_table()
    assert narrative_arrow.num_rows == 5
    assert sorted(narrative_arrow.column_names) == [
        "city",
        "cost_usd",
        "model_id",
        "narrative",
    ]
    # All narratives produced by the mocked agent
    assert all(
        m == "claude_sonnet_4_6"
        for m in narrative_arrow["model_id"].to_pylist()
    )
    assert pc.sum(narrative_arrow["cost_usd"]).as_py() == pytest.approx(0.0005)

    fig = OpenMeteoCityTempMeanFigure(WeatherVersions.MAIN)
    fig.make(replace=True)

    assert fig.path_to_format(fb.FigureFormat.PKL).exists()

    doc = WeatherReportDoc(WeatherVersions.MAIN)
    doc.make(replace=True)

    md_text = doc.path_to_format(fb.DocumentFormat.MD).read_text()
    assert "Weather summary" in md_text
    assert "<svg" in md_text  # SVG embedded
    assert "| city |" in md_text or "|city|" in md_text  # markdown table
    assert "Mock narrative" in md_text  # agent narratives embedded

    # Convert demonstration: CSV side-format on the summary parquet.
    summary.convert(fb.TableFormat.CSV)
    assert summary.path_to_format(fb.TableFormat.CSV).exists()

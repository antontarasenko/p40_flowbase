"""Smoke test for p40_weather: imports and end-to-end build with mocked HTTP."""

import json
from unittest.mock import patch

import p40_flowbase as fb
import pytest
import sqlmodel as sm


@pytest.fixture
def local_data(tmp_path):
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


def test_imports():
    """Every public symbol importable."""
    from p40_weather.definitions import defs
    from p40_weather.helpers import build_forecast_url
    from p40_weather.objects import (
        WeatherDoc,
        WeatherFigure,
        WeatherHourlyTable,
        WeatherHTTPDB,
        WeatherInputCities,
        WeatherResponseFiles,
        WeatherSummaryTable,
        WeatherVersions,
    )

    assert defs is not None
    assert WeatherVersions.MAIN.value.forecast_days == 1
    assert WeatherVersions.BACKFILL_2025.value.forecast_days == 16
    assert build_forecast_url(latitude=0.0, longitude=0.0).startswith(
        "https://api.open-meteo.com/v1/forecast?"
    )
    assert WeatherInputCities.id == "weather_input_cities"
    from p40_weather.objects import WeatherVersionConfig
    assert WeatherVersionConfig.id == "weather_version_config"
    assert WeatherHTTPDB.id == "weather_http_db"
    assert WeatherResponseFiles.id == "weather_response_files"
    assert WeatherHourlyTable.id == "weather_hourly_table"
    assert WeatherSummaryTable.id == "weather_summary_table"
    assert WeatherFigure.id == "weather_figure"
    assert WeatherDoc.id == "weather_doc"


def test_end_to_end_with_mocked_http(local_data):
    """Run the full pipeline against canned Open-Meteo responses."""
    from p40_weather.objects import (
        WeatherCityNarrativeAgentDB,
        WeatherCityNarrativeTable,
        WeatherDoc,
        WeatherFigure,
        WeatherHourlyTable,
        WeatherHTTPDB,
        WeatherInputCities,
        WeatherResponseFiles,
        WeatherSummaryTable,
        WeatherVersions,
    )

    # Materialize the cities catalog first; downstream stages read from it.
    cities_obj = WeatherInputCities(WeatherVersions.MAIN)
    cities_obj.make(replace=True)
    assert cities_obj.df.num_rows == 5
    assert sorted(cities_obj.df.column_names) == [
        "latitude",
        "longitude",
        "name",
    ]

    canned: dict[tuple[float, float], str] = {
        (row["latitude"], row["longitude"]): _canned_response(
            row["latitude"], row["longitude"],
        )
        for row in cities_obj.df.to_pylist()
    }

    async def fake_execute_http_request(
        self,
        http_client,
        request_method,
        request_url,
        request_headers,
        request_body,
        ephemeral_headers=None,
    ):
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
            db = WeatherHTTPDB(WeatherVersions.MAIN)
            await db.make(replace=True)
            await db.close()

        asyncio.run(_run())

    # Audit: WeatherHTTPRequestGroup carries the version metadata.
    from p40_weather.objects.weather import (
        WeatherHTTPRequestExtra,
        WeatherHTTPRequestGroup,
    )

    async def _check_extras() -> None:
        db = WeatherHTTPDB(WeatherVersions.MAIN)
        try:
            async with db.session_factory() as session:
                groups = (
                    await session.exec(sm.select(WeatherHTTPRequestGroup))
                ).all()
                extras = (
                    await session.exec(sm.select(WeatherHTTPRequestExtra))
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

    files_obj = WeatherResponseFiles(WeatherVersions.MAIN)
    files_obj.make(replace=True)

    files_dir = files_obj.path_to_format(fb.CompositeFormat.FILES)
    assert len(list(files_dir.glob("*.json"))) == 5

    hourly = WeatherHourlyTable(WeatherVersions.MAIN)
    hourly.make(replace=True)
    assert hourly.df.num_rows == 15  # 5 cities x 3 hours
    assert sorted(hourly.df.column_names) == [
        "city",
        "precip_mm",
        "temp_c",
        "ts_utc",
    ]

    summary = WeatherSummaryTable(WeatherVersions.MAIN)
    summary.make(replace=True)
    assert summary.df.num_rows == 5
    assert sorted(summary.df.column_names) == [
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

    async def _fake_anthropic(self, task):
        del self
        from p40_weather.objects import WeatherCityNarrativeAgentDB
        now = datetime.now(UTC)
        async with WeatherCityNarrativeAgentDB(
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
            db = WeatherCityNarrativeAgentDB(WeatherVersions.MAIN)
            await db.make(replace=True)
            await db.close()

        asyncio.run(_run_agent())

    narrative_table = WeatherCityNarrativeTable(WeatherVersions.MAIN)
    narrative_table.make(replace=True)
    assert narrative_table.df.num_rows == 5
    assert sorted(narrative_table.df.column_names) == [
        "city",
        "cost_usd",
        "model_id",
        "narrative",
    ]
    # All narratives produced by the mocked agent
    assert all(
        m == "claude_sonnet_4_6"
        for m in narrative_table.df["model_id"].to_pylist()
    )
    assert sum(narrative_table.df["cost_usd"].to_pylist()) == pytest.approx(0.0005)

    fig = WeatherFigure(WeatherVersions.MAIN)
    fig.make(replace=True)

    assert fig.path_to_format(fb.FigureFormat.PKL).exists()

    doc = WeatherDoc(WeatherVersions.MAIN)
    doc.make(replace=True)

    md_text = doc.path_to_format(fb.DocumentFormat.MD).read_text()
    assert "Weather summary" in md_text
    assert "<svg" in md_text  # SVG embedded
    assert "| city |" in md_text or "|city|" in md_text  # markdown table
    assert "Mock narrative" in md_text  # agent narratives embedded

    # Convert demonstration: CSV side-format on the summary parquet.
    summary.convert(fb.TableFormat.CSV)
    assert summary.path_to_format(fb.TableFormat.CSV).exists()

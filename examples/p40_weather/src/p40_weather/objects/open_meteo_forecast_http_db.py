"""``OpenMeteoForecastHTTPDB``: SQLite of Open-Meteo requests, plus its audit tables."""

import uuid
from enum import Enum
from typing import (
    Any,
    ClassVar,
)

import p40_flowbase as fb
from p40_flowbase import checks as ck

from p40_weather.helpers import build_forecast_url
from p40_weather.objects.manual_input_cities_table import ManualInputCitiesTable
from p40_weather.objects.versions import (
    SUPPORTED_VERSIONS,
    narrow_version,
)

#: Per-run audit row. One row inserted by ``_populate_http_requests``;
#: captures the ``WeatherVersion`` parameters at populate time so later
#: queries against the DB don't need to re-look up the version metadata
#: (and so changes to ``WeatherVersions`` after a run can't rewrite history).
OpenMeteoHTTPRequestGroup = fb.make_http_request_group_table(
    "open_meteo",
    version_id=str,
    forecast_days=int,
    cities_count=int,
)

#: Per-request metadata. One row per ``fb.HTTPRequest``, joined via
#: ``fb.HTTPRequest.http_request_extra_id``. Lets downstream consumers
#: read the city name and coordinates straight off the join instead
#: of parsing the URL or re-resolving the version's city catalog.
OpenMeteoHTTPRequestExtra = fb.make_http_request_extra_table(
    "open_meteo",
    city_name=str,
    latitude_deg=float,
    longitude_deg=float,
)


@fb.asset(deps=fb.AUTO)
class OpenMeteoForecastHTTPDB(fb.HTTPDB):
    """SQLite of HTTP requests against Open-Meteo, one row per city.

    Each ``make()`` call writes:

    * one ``OpenMeteoHTTPRequestGroup`` row carrying the version's
      audit fields (``version_id``, ``forecast_days``, ``cities_count``).
    * one ``OpenMeteoHTTPRequestExtra`` row per city with denormalized
      ``city_name`` / ``latitude_deg`` / ``longitude_deg``.
    * one ``fb.HTTPRequest`` row per city, FK-linked to both extras.
    """

    id: ClassVar[str] = "open_meteo_forecast_http_db"
    description: ClassVar[str] = (
        "HTTP requests for hourly forecasts (cities + days from the version)."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    tables: ClassVar[list[Any]] = [
        OpenMeteoHTTPRequestGroup,
        OpenMeteoHTTPRequestExtra,
        fb.HTTPRequest,
    ]
    # Catch zero-row populates and any 4xx/5xx response from Open-Meteo.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.MinRequests(1),
        ck.MaxFailureRate(frac=0.0),
    )

    # Open-Meteo free-tier rate limits (per their docs, 2026): 10 req/s,
    # 600 req/min, 5_000 req/h, 10_000 req/day. We pick 3/s for headroom
    # under the per-second cap and to play nicely with concurrent runs in
    # the same workspace. Override via ``make(rate_limit=..., rate_period=...)``
    # if you have a paid plan with higher limits.
    rate_limit: ClassVar[float] = 3.0
    rate_period: ClassVar[float] = 1.0

    async def _populate_http_requests(self) -> uuid.UUID:
        wv = narrow_version(self.version)
        # Pattern: project exactly the columns needed, in SQL, then cross
        # into Python via .to_arrow_table().to_pylist(). Small catalog, so
        # a full materialize is fine.
        cities_rows: list[dict[str, Any]] = (
            ManualInputCitiesTable(self.version)
            .sql("SELECT name, latitude_deg, longitude_deg FROM t")
            .to_arrow_table()
            .to_pylist()
        )
        group_id = uuid.uuid4()
        async with self.session_factory() as session:
            session.add(
                OpenMeteoHTTPRequestGroup(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                    http_request_group_id=group_id,
                    created_by_class=type(self).__name__,
                    version_id=wv.id,
                    forecast_days=wv.forecast_days,
                    cities_count=len(cities_rows),
                )
            )
            for row in cities_rows:
                name = row["name"]
                lat = row["latitude_deg"]
                lon = row["longitude_deg"]
                extra_id = uuid.uuid4()
                session.add(
                    OpenMeteoHTTPRequestExtra(  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
                        http_request_extra_id=extra_id,
                        city_name=name,
                        latitude_deg=lat,
                        longitude_deg=lon,
                    )
                )
                session.add(
                    fb.HTTPRequest(
                        request_url=build_forecast_url(
                            latitude=lat,
                            longitude=lon,
                            forecast_days=wv.forecast_days,
                        ),
                        request_method="GET",
                        http_request_group_id=group_id,
                        http_request_extra_id=extra_id,
                    )
                )
            await session.commit()
        return group_id

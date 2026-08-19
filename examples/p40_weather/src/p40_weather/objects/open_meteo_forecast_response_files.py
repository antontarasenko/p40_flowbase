"""``OpenMeteoForecastResponseFiles``: one JSON file per successful HTTP response."""

from enum import Enum
from typing import (
    ClassVar,
    override,
)

import p40_flowbase as fb
import sqlmodel as sm
from p40_flowbase import checks as ck

from p40_weather.objects.open_meteo_forecast_http_db import (
    OpenMeteoForecastHTTPDB,
    OpenMeteoHTTPRequestExtra,
)
from p40_weather.objects.versions import SUPPORTED_VERSIONS


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_")


@fb.asset(deps=fb.AUTO)
class OpenMeteoForecastResponseFiles(fb.Composite):
    """One ``<city>.json`` file per successful HTTP response.

    The city name comes straight from a join on
    ``OpenMeteoHTTPRequestExtra``, no URL parsing, no reverse lat/lon
    lookup. This is the payoff of the per-request Extra table.
    """

    id: ClassVar[str] = "open_meteo_forecast_response_files"
    description: ClassVar[str] = "Per-city Open-Meteo JSON responses."
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    # Documents the whole output in one glob: the bundle is nothing but
    # <city>.json files. Rendered verbatim in readme.html; expanded to the
    # actual filenames in meta.json.
    expected_files: ClassVar[tuple[fb.FileSpec, ...]] = (
        fb.FileSpec(
            "*.json",
            "One Open-Meteo JSON response per city, named <city>.json.",
        ),
    )
    # Coverage on an auto-built Composite: AllExpectedFilesPresent makes the
    # *.json spec match at least one file (so it subsumes MinFiles(1) here),
    # and NoUnindexedFiles forbids any stray file that is not a documented
    # city JSON. NoEmptyFiles still catches truncated 0-byte downloads.
    checks: ClassVar[tuple[fb.Check, ...]] = (
        ck.AllExpectedFilesPresent(),
        ck.NoUnindexedFiles(),
        ck.NoEmptyFiles(),
    )

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(fb.CompositeFormat.FILES)
        files_dir.mkdir(parents=True, exist_ok=True)

        async def _dump() -> None:
            db = OpenMeteoForecastHTTPDB(self.version)
            try:
                async with db.session_factory() as session:
                    rows = (
                        await session.exec(
                            sm.select(fb.HTTPRequest, OpenMeteoHTTPRequestExtra)
                            .join(
                                OpenMeteoHTTPRequestExtra,
                                fb.HTTPRequest.http_request_extra_id  # type: ignore[arg-type]
                                == OpenMeteoHTTPRequestExtra.http_request_extra_id,  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
                            )
                            .where(fb.HTTPRequest.response_status == 200)
                        )
                    ).all()
                for req, extra in rows:
                    body = req.response_body_text or ""
                    city = extra.city_name  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
                    (files_dir / f"{_slugify(city)}.json").write_text(body)
            finally:
                await db.close()

        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_dump())
        else:
            msg = "OpenMeteoForecastResponseFiles._make cannot run inside an event loop."
            raise RuntimeError(msg)

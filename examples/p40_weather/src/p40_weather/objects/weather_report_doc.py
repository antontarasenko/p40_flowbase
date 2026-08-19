"""``WeatherReportDoc``: Markdown report with embedded SVG and agent narratives."""

import datetime as _dt
import io
from enum import Enum
from typing import (
    ClassVar,
    override,
)

import p40_flowbase as fb
import pyarrow as pa

from p40_weather.objects.anthropic_city_narrative_table import AnthropicCityNarrativeTable
from p40_weather.objects.open_meteo_city_temp_mean_figure import OpenMeteoCityTempMeanFigure
from p40_weather.objects.open_meteo_city_summary_table import OpenMeteoCitySummaryTable
from p40_weather.objects.versions import SUPPORTED_VERSIONS


def _markdown_table(arrow: pa.Table) -> str:
    """Render a small pyarrow table as a GitHub-flavored Markdown table."""
    cols = arrow.column_names
    rows = arrow.to_pylist()
    buf = io.StringIO()
    buf.write("| " + " | ".join(cols) + " |\n")
    buf.write("| " + " | ".join("---" for _ in cols) + " |\n")
    for r in rows:
        formatted = [
            f"{r[c]:.2f}" if isinstance(r[c], float) else str(r[c])
            for c in cols
        ]
        buf.write("| " + " | ".join(formatted) + " |\n")
    return buf.getvalue()


@fb.asset(deps=fb.AUTO, convert_formats=[fb.DocumentFormat.PDF])
class WeatherReportDoc(fb.Document):
    """Markdown report: summary table + embedded SVG + agent narratives."""

    id: ClassVar[str] = "weather_report_doc"
    description: ClassVar[str] = "Per-city weather report."
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    template_package: ClassVar[str | None] = "p40_weather"

    @override
    def _make_data(self) -> None:
        figure = OpenMeteoCityTempMeanFigure(self.version)
        svg_path = figure.path_to_format(fb.FigureFormat.SVG)
        if not svg_path.exists():
            figure.convert(fb.FigureFormat.SVG)
        svg_text = svg_path.read_text()

        summary = OpenMeteoCitySummaryTable(self.version)

        # Pattern: a headline answered by a scalar query, straight from the
        # parquet — .fetchone() never materializes the table. The summary
        # always has >=1 row (its MinRows check), so the row is non-None.
        warmest = summary.sql(
            "SELECT city, temp_mean_c FROM t ORDER BY temp_mean_c DESC LIMIT 1"
        ).fetchone()
        assert warmest is not None
        warmest_city, peak_mean_c = warmest
        headline = (
            f"Warmest city: {warmest_city} ({peak_mean_c:.1f} °C mean)."
        )

        # Pattern: materialize the small summary once, ordered, for the table.
        summary_table = _markdown_table(
            summary.sql("SELECT * FROM t ORDER BY city").to_arrow_table()
        )

        # Pattern: project only the columns the report renders.
        narratives = (
            AnthropicCityNarrativeTable(self.version)
            .sql("SELECT city, narrative FROM t ORDER BY city")
            .to_arrow_table()
            .to_pylist()
        )

        self.data = {
            "headline": headline,
            "summary_table": summary_table,
            "figure_svg": svg_text,
            "narratives": narratives,
            "run_date": _dt.datetime.now(_dt.UTC).date().isoformat(),
        }

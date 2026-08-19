"""``OpenMeteoCityTempMeanFigure``: bar chart of mean temperatures."""

import pickle
import warnings
from enum import Enum
from typing import (
    ClassVar,
    override,
)

import matplotlib

matplotlib.use("Agg")  # headless: Dagster runs each asset in a non-GUI subprocess

import matplotlib.pyplot as plt  # must follow matplotlib.use(...)
import p40_flowbase as fb

from p40_weather.objects.open_meteo_city_summary_table import OpenMeteoCitySummaryTable
from p40_weather.objects.versions import SUPPORTED_VERSIONS


@fb.asset(deps=fb.AUTO)
class OpenMeteoCityTempMeanFigure(fb.Figure):
    """Bar chart of mean temperature by city."""

    id: ClassVar[str] = "open_meteo_city_temp_mean_figure"
    description: ClassVar[str] = "Mean temperature bar chart."
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS

    @override
    def _make(self) -> None:
        # Pattern: project the two columns the chart needs, ordered, then
        # bind the pyarrow table to a local and reuse it (the local is the
        # cache — fine here because the summary is one row per city).
        summary = (
            OpenMeteoCitySummaryTable(self.version)
            .sql("SELECT city, temp_mean_c FROM t ORDER BY city")
            .to_arrow_table()
        )
        cities: list[str] = summary["city"].to_pylist()  # type: ignore[assignment]
        means: list[float] = summary["temp_mean_c"].to_pylist()  # type: ignore[assignment]

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(cities, means)
        ax.set_ylabel("Mean temperature (°C)")
        ax.set_title("Mean temperature by city")
        fig.tight_layout()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        with open(self.path_to_format(fb.FigureFormat.PKL), "wb") as f:
            # matplotlib figures pickle internal itertools state; Python 3.14
            # deprecates that, but we don't use the affected APIs.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    category=DeprecationWarning,
                    message="Pickle, copy, and deepcopy",
                )
                pickle.dump(fig, f)
        plt.close(fig)

"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import pickle
from enum import Enum
from typing import ClassVar

from matplotlib.figure import Figure as MplFigure

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import FigureFormat
from p40_flowbase.logging import logger


class Figure(DataObject):
    """Base class for single figure data objects.

    Figure objects store matplotlib figures.
    Supported formats:
        - PKL: Pickled matplotlib figure (default)
        - PDF: PDF document
        - PNG: PNG image
        - SVG: SVG vector graphics
    """

    make_format: ClassVar[FigureFormat] = FigureFormat.PKL  # pyright: ignore[reportIncompatibleVariableOverride]

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self._mplf: MplFigure | None = None

    @property
    def mplf(self) -> MplFigure:
        """Return the matplotlib figure (lazy loading)."""
        if self._mplf is None:
            with open(self.path_to_format(FigureFormat.PKL), "rb") as f:
                loaded: MplFigure = pickle.load(f)  # noqa: S301  # internal cache file we wrote ourselves
            self._mplf = loaded
        return self._mplf

    def _convert_to_pdf(self) -> None:
        """Convert pkl to pdf."""
        fig = self.mplf
        pdf_path = self.path_to_format(FigureFormat.PDF)
        fig.savefig(pdf_path, format="pdf", bbox_inches="tight")
        logger.info(f"Converted to PDF: {pdf_path}")

    def _convert_to_png(self) -> None:
        """Convert pkl to png."""
        fig = self.mplf
        png_path = self.path_to_format(FigureFormat.PNG)
        fig.savefig(png_path, format="png", bbox_inches="tight", dpi=300)
        logger.info(f"Converted to PNG: {png_path}")

    def _convert_to_svg(self) -> None:
        """Convert pkl to svg."""
        fig = self.mplf
        svg_path = self.path_to_format(FigureFormat.SVG)
        fig.savefig(svg_path, format="svg", bbox_inches="tight")
        logger.info(f"Converted to SVG: {svg_path}")

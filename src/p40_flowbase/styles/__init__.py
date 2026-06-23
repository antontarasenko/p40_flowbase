"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from typing import (
    Any,
)

import matplotlib.pyplot as plt

STYLES: dict[str, dict[str, Any]] = {
    "style_1": {
        "beamer": {
            "theme": "metropolis",
        },
        "mpl": {
            "patch.linewidth": 0,
            "font.family": "sans-serif",
            "font.sans-serif": ["Fira Sans", "Helvetica", "Arial", "DejaVu Sans"],
            "font.monospace": ["Fira Mono", "Courier New", "DejaVu Sans Mono"],
            "font.size": 12,
            "text.usetex": False,
            "axes.formatter.use_locale": True,
            "axes.labelsize": 12,
            "axes.titlesize": 14,
            "axes.spines.left": False,
            "axes.spines.bottom": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.xmargin": 0.1,
            "axes.ymargin": 0.1,
            "axes.zmargin": 0.1,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.facecolor": (0, 0, 0, 0),
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "grid.linestyle": (1, 5),
            "figure.figsize": (6, 4),
            "figure.dpi": 100,
            "figure.autolayout": True,
            "figure.facecolor": (0, 0, 0, 0),
            "savefig.facecolor": (0, 0, 0, 0),
            "savefig.edgecolor": (0, 0, 0, 0),
            "legend.fontsize": 12,
            "legend.facecolor": (0, 0, 0, 0),
            "legend.edgecolor": (0, 0, 0, 0),
            "legend.framealpha": 0,
        },
    }
}


def apply_style(style_name: str = "style_1") -> None:
    """Apply matplotlib style settings.

    :param style_name: Name of the style to apply from the ``STYLES``
        dict.
    :raises KeyError: If ``style_name`` is not found in ``STYLES``.

    Example::

        from p40_flowbase.styles import apply_style
        apply_style("style_1")
    """
    if style_name not in STYLES:
        raise KeyError(
            f"Style '{style_name}' not found. Available styles: {list(STYLES.keys())}"
        )

    mpl_settings = STYLES[style_name].get("mpl", {})
    for key, value in mpl_settings.items():
        plt.rcParams[key] = value


__all__ = ["STYLES", "apply_style"]

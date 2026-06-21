"""p40_weather: worked example for p40_flowbase.

Builds an eight-stage pipeline against the Open-Meteo API. See
``p40_weather.definitions`` for the Dagster wiring and
``p40_weather.objects.weather`` for the DataObject subclasses.
"""

from p40_weather._version import __version__

__all__ = [
    "__version__",
]

"""Open-Meteo API wrapper.

The free Open-Meteo forecast endpoint accepts ``latitude``,
``longitude``, and a comma-separated ``hourly`` variable list. No auth
required. See https://open-meteo.com/en/docs for the schema.

Cities are not defined here anymore — each version's catalog lives in
``resources/versions/weather_versions/cities-<id>.tsv`` and is
materialized by ``WeatherInputCities`` (see
``p40_weather.objects.weather``).
"""

from urllib.parse import urlencode

_BASE_URL = "https://api.open-meteo.com/v1/forecast"


def build_forecast_url(
    *,
    latitude: float,
    longitude: float,
    hourly: tuple[str, ...] = ("temperature_2m", "precipitation"),
    forecast_days: int = 1,
) -> str:
    """Build a fully-qualified Open-Meteo forecast URL.

    :param latitude: Latitude in decimal degrees.
    :type latitude: float
    :param longitude: Longitude in decimal degrees.
    :type longitude: float
    :param hourly: Hourly variables to request.
    :type hourly: tuple[str, ...]
    :param forecast_days: Number of forecast days (1..16).
    :type forecast_days: int
    :returns: Full URL with query string.
    :rtype: str
    """
    qs = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(hourly),
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }
    )
    return f"{_BASE_URL}?{qs}"

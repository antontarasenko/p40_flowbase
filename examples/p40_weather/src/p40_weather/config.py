"""Settings for p40_weather, read from environment variables.

``WeatherSettings`` overrides ``BaseFlowSettings.model_config`` to set
``env_prefix=""`` so env vars like ``LOCAL_DATA`` and
``ANTHROPIC_API_KEY`` are read straight off the environment, no
project prefix. This is the conventional shape for a worked downstream
example. Real projects can either keep the empty prefix or pick a
project-specific one.
"""

import pydantic_settings

import p40_flowbase as fb


class WeatherSettings(fb.BaseFlowSettings):
    """Project settings, env-var driven, no prefix.

    Inherits ``local_data: str`` (required, no default) from
    ``fb.BaseFlowSettings``. Instantiating ``WeatherSettings()``
    without ``LOCAL_DATA`` set in the environment raises
    ``pydantic.ValidationError`` immediately at import time, which is
    exactly the loud failure we want for misconfigured deployments.
    """

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


#: Module-level singleton. ``LOCAL_DATA`` must be set before this
#: module is imported (typically in the shell that runs ``dg dev`` /
#: ``dg launch``, or via a ``conftest.py`` for tests). pydantic-settings
#: populates required fields from the env at runtime, but pyright
#: insists on the constructor signature, hence the ignore.
settings = WeatherSettings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]

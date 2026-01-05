"""Configuration for weather_report project."""

import pydantic_settings

from p40_flowbase import BaseFlowSettings


class Settings(BaseFlowSettings):
    """Weather report project configuration loaded from environment variables."""

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="WEATHER_REPORT_",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

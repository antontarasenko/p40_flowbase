"""Configuration for web_archive project."""

import pydantic_settings

from p40_flowbase import BaseFlowSettings


class Settings(BaseFlowSettings):
    """Web archive project configuration loaded from environment variables."""

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="WEB_ARCHIVE_",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()

"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import pydantic_settings


class BaseFlowSettings(pydantic_settings.BaseSettings):
    """Base configuration settings for data flow projects.

    Subclasses should set model_config with appropriate env_prefix.

    Example:
        class MyProjectSettings(BaseFlowSettings):
            model_config = pydantic_settings.SettingsConfigDict(
                env_prefix="MY_PROJECT_",
                case_sensitive=False,
                extra="ignore",
            )
            custom_field: str = "default"

        settings = MyProjectSettings()
    """

    model_config = pydantic_settings.SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    style: str = "style_1"
    local_data: str

    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    openai_api_key: str | None = None


__all__ = ["BaseFlowSettings"]

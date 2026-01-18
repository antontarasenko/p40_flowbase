"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from dataclasses import dataclass
from enum import (
    Enum,
    StrEnum,
)


class AgentProviders(StrEnum):
    """Supported agent providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class AgentModelVersion:
    """Agent model version metadata.

    Attributes:
        id: Internal identifier for the model.
        api_id: API identifier used when making requests.
        name: Human-readable name.
        provider: The provider this model belongs to.
    """

    id: str
    api_id: str
    name: str
    provider: AgentProviders


class AgentModels(Enum):
    """Available agent models across providers."""

    CLAUDE_OPUS_4_5 = AgentModelVersion(
        id="claude_opus_4_5_20251101",
        api_id="claude-opus-4-5-20251101",
        name="Claude Opus 4.5",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_SONNET_4_5 = AgentModelVersion(
        id="claude_sonnet_4_5_20250929",
        api_id="claude-sonnet-4-5-20250929",
        name="Claude Sonnet 4.5",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_HAIKU_4_5 = AgentModelVersion(
        id="claude_haiku_4_5_20251001",
        api_id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider=AgentProviders.ANTHROPIC,
    )

    GPT_5_2 = AgentModelVersion(
        id="gpt_5_2",
        api_id="gpt-5.2",
        name="GPT-5.2",
        provider=AgentProviders.OPENAI,
    )
    GPT_5 = AgentModelVersion(
        id="gpt_5",
        api_id="gpt-5",
        name="GPT-5",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_MINI = AgentModelVersion(
        id="gpt_5_mini",
        api_id="gpt-5-mini",
        name="GPT-5 Mini",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_NANO = AgentModelVersion(
        id="gpt_5_nano",
        api_id="gpt-5-nano",
        name="GPT-5 Nano",
        provider=AgentProviders.OPENAI,
    )

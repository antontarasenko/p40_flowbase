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

    # OpenAI models (via openai-agents SDK)
    OPENAI_GPT_5_2 = AgentModelVersion(
        id="openai_gpt_5_2",
        api_id="gpt-5-2",
        name="GPT-5.2",
        provider=AgentProviders.OPENAI,
    )
    OPENAI_GPT_5 = AgentModelVersion(
        id="openai_gpt_5",
        api_id="gpt-5",
        name="GPT-5",
        provider=AgentProviders.OPENAI,
    )
    OPENAI_GPT_5_MINI = AgentModelVersion(
        id="openai_gpt_5_mini",
        api_id="gpt-5-mini",
        name="GPT-5 Mini",
        provider=AgentProviders.OPENAI,
    )
    OPENAI_GPT_5_NANO = AgentModelVersion(
        id="openai_gpt_5_nano",
        api_id="gpt-5-nano",
        name="GPT-5 Nano",
        provider=AgentProviders.OPENAI,
    )

    # Anthropic models (via claude-agent-sdk)
    ANTHROPIC_OPUS = AgentModelVersion(
        id="anthropic_opus",
        api_id="opus",
        name="Claude Opus",
        provider=AgentProviders.ANTHROPIC,
    )
    ANTHROPIC_SONNET = AgentModelVersion(
        id="anthropic_sonnet",
        api_id="sonnet",
        name="Claude Sonnet",
        provider=AgentProviders.ANTHROPIC,
    )
    ANTHROPIC_HAIKU = AgentModelVersion(
        id="anthropic_haiku",
        api_id="haiku",
        name="Claude Haiku",
        provider=AgentProviders.ANTHROPIC,
    )

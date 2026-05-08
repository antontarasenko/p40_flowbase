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

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class AgentEffort(StrEnum):
    """Reasoning effort levels for agent tasks.

    Supported by Anthropic Claude Agent SDK (low, medium, high, max) and
    OpenAI Agents SDK (none, minimal, low, medium, high, xhigh).
    """

    HIGH = "high"
    LOW = "low"
    MAX = "max"
    MEDIUM = "medium"
    MINIMAL = "minimal"
    NONE = "none"
    XHIGH = "xhigh"


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

    @classmethod
    def by_id(cls, model_id: str) -> "AgentModels":
        """Resolve an ``AgentModels`` member by its ``value.id``.

        Raises:
            ValueError: If no member with the given ID exists.
        """
        for member in cls:
            if member.value.id == model_id:
                return member
        raise ValueError(f"Unknown agent model ID: {model_id}")

    CLAUDE_HAIKU_4_5 = AgentModelVersion(
        id="claude_haiku_4_5_20251001",
        api_id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_OPUS_4_5 = AgentModelVersion(
        id="claude_opus_4_5_20251101",
        api_id="claude-opus-4-5-20251101",
        name="Claude Opus 4.5",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_OPUS_4_6 = AgentModelVersion(
        id="claude_opus_4_6",
        api_id="claude-opus-4-6",
        name="Claude Opus 4.6",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_OPUS_4_7 = AgentModelVersion(
        id="claude_opus_4_7",
        api_id="claude-opus-4-7",
        name="Claude Opus 4.7",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_SONNET_4_5 = AgentModelVersion(
        id="claude_sonnet_4_5_20250929",
        api_id="claude-sonnet-4-5-20250929",
        name="Claude Sonnet 4.5",
        provider=AgentProviders.ANTHROPIC,
    )
    CLAUDE_SONNET_4_6 = AgentModelVersion(
        id="claude_sonnet_4_6",
        api_id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider=AgentProviders.ANTHROPIC,
    )
    GPT_5 = AgentModelVersion(
        id="gpt_5",
        api_id="gpt-5",
        name="GPT-5",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_2 = AgentModelVersion(
        id="gpt_5_2",
        api_id="gpt-5.2",
        name="GPT-5.2",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_4 = AgentModelVersion(
        id="gpt_5_4",
        api_id="gpt-5.4",
        name="GPT-5.4",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_4_MINI = AgentModelVersion(
        id="gpt_5_4_mini",
        api_id="gpt-5.4-mini",
        name="GPT-5.4 Mini",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_5 = AgentModelVersion(
        id="gpt_5_5",
        api_id="gpt-5.5",
        name="GPT-5.5",
        provider=AgentProviders.OPENAI,
    )
    GPT_5_5_PRO = AgentModelVersion(
        id="gpt_5_5_pro",
        api_id="gpt-5.5-pro",
        name="GPT-5.5 Pro",
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

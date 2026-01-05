"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from dataclasses import dataclass
from enum import (
    Enum,
    StrEnum,
)


class LLMProviders(StrEnum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENAI = "openai"


@dataclass(frozen=True)
class LLMModelVersion:
    """Metadata for an LLM model.

    Attributes:
        id: Internal identifier for the model.
        api_id: API identifier used in requests.
        name: Human-readable name.
        provider: LLM provider (Anthropic, Google, OpenAI).
        input_token_price_usd: Cost per input token in USD.
        output_token_price_usd: Cost per output token in USD.
    """

    id: str
    api_id: str
    name: str
    provider: LLMProviders
    input_token_price_usd: float
    output_token_price_usd: float


class LLMModels(Enum):
    """Available LLM models with pricing information."""

    CLAUDE_OPUS_4_5 = LLMModelVersion(
        id="claude_opus_4_5_20251101",
        api_id="claude-opus-4-5-20251101",
        name="Claude Opus 4.5",
        provider=LLMProviders.ANTHROPIC,
        input_token_price_usd=0.000005000,
        output_token_price_usd=0.000025000,
    )
    CLAUDE_SONNET_4_5 = LLMModelVersion(
        id="claude_sonnet_4_5_20250929",
        api_id="claude-sonnet-4-5-20250929",
        name="Claude Sonnet 4.5",
        provider=LLMProviders.ANTHROPIC,
        input_token_price_usd=0.000003000,
        output_token_price_usd=0.000015000,
    )
    CLAUDE_HAIKU_4_5 = LLMModelVersion(
        id="claude_haiku_4_5_20251001",
        api_id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider=LLMProviders.ANTHROPIC,
        input_token_price_usd=0.000001000,
        output_token_price_usd=0.000005000,
    )
    GEMINI_3_PRO = LLMModelVersion(
        id="gemini_3_pro_preview",
        api_id="gemini-3-pro-preview",
        name="Gemini 3 Pro",
        provider=LLMProviders.GOOGLE,
        input_token_price_usd=0.000002000,
        output_token_price_usd=0.000012000,
    )
    GEMINI_3_FLASH = LLMModelVersion(
        id="gemini_3_flash_preview",
        api_id="gemini-3-flash-preview",
        name="Gemini 3 Flash",
        provider=LLMProviders.GOOGLE,
        input_token_price_usd=0.000000500,
        output_token_price_usd=0.000003000,
    )
    GEMINI_2_5_PRO = LLMModelVersion(
        id="gemini_2_5_pro",
        api_id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        provider=LLMProviders.GOOGLE,
        input_token_price_usd=0.000001250,
        output_token_price_usd=0.000010000,
    )
    GEMINI_2_5_FLASH = LLMModelVersion(
        id="gemini_2_5_flash",
        api_id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        provider=LLMProviders.GOOGLE,
        input_token_price_usd=0.000000300,
        output_token_price_usd=0.000002500,
    )
    GEMINI_2_5_FLASH_LITE = LLMModelVersion(
        id="gemini_2_5_flash_lite",
        api_id="gemini-2.5-flash-lite",
        name="Gemini 2.5 Flash Lite",
        provider=LLMProviders.GOOGLE,
        input_token_price_usd=0.000000100,
        output_token_price_usd=0.000000400,
    )
    GPT_5_2 = LLMModelVersion(
        id="gpt_5_2",
        api_id="gpt-5.2",
        name="GPT-5.2",
        provider=LLMProviders.OPENAI,
        input_token_price_usd=0.000001750,
        output_token_price_usd=0.000014000,
    )
    GPT_5 = LLMModelVersion(
        id="gpt_5",
        api_id="gpt-5",
        name="GPT-5",
        provider=LLMProviders.OPENAI,
        input_token_price_usd=0.000001250,
        output_token_price_usd=0.000010000,
    )
    GPT_5_MINI = LLMModelVersion(
        id="gpt_5_mini",
        api_id="gpt-5-mini",
        name="GPT-5 Mini",
        provider=LLMProviders.OPENAI,
        input_token_price_usd=0.000000250,
        output_token_price_usd=0.000002000,
    )
    GPT_5_NANO = LLMModelVersion(
        id="gpt_5_nano",
        api_id="gpt-5-nano",
        name="GPT-5 Nano",
        provider=LLMProviders.OPENAI,
        input_token_price_usd=0.000000050,
        output_token_price_usd=0.000000400,
    )

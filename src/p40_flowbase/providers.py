"""Shared provider, model, and registry definitions.

The catalog (``Models``) is curated but **open**: there is no closed enum at
the type level or in the DB. Downstream code adds models in any of three
type-safe ways.

Adding a model
==============

1. **Use a built-in.** ``Models.CLAUDE_OPUS_4_7`` is a ``ModelVersion``
   directly usable wherever a spec is expected.

   .. code:: python

      from p40_flowbase.providers import Models
      from p40_flowbase.llm.models import LLMRequest

      LLMRequest.from_spec(Models.CLAUDE_OPUS_4_7, user_prompt="hi")

2. **Construct ad hoc.** Build a ``ModelVersion`` inline — useful for dated
   snapshots, fine-tunes, OpenAI-compatible proxy endpoints, anything not in
   the curated catalog.

   .. code:: python

      from p40_flowbase.providers import ModelVersion, Providers

      MY_PROXY = ModelVersion(
          id="my_proxy_gpt",
          api_id="custom-proxy-gpt-5-5",
          name="Internal proxy (GPT-5.5)",
          provider=Providers.OPENAI,
          # Pricing is optional. When set, ``LLMRequest`` /
          # ``AgentTask`` populate ``expected_input_cost_usd``.
          input_token_price_usd=0.000005,
          output_token_price_usd=0.000030,
      )
      LLMRequest.from_spec(MY_PROXY, user_prompt="...")

3. **Subclass ``Models``** when grouping several custom entries together —
   this preserves the ``Models.X`` autocomplete pattern in your codebase
   alongside the built-ins.

   .. code:: python

      from typing import ClassVar
      from p40_flowbase.providers import Models, ModelVersion, Providers

      class MyModels(Models):
          CLAUDE_OPUS_4_7_DATED: ClassVar[ModelVersion] = ModelVersion(
              id="claude_opus_4_7_20260416",
              api_id="claude-opus-4-7-20260416",
              name="Claude Opus 4.7 (2026-04-16 snapshot)",
              provider=Providers.ANTHROPIC,
              input_token_price_usd=0.000005,
              output_token_price_usd=0.000025,
          )

      LLMRequest.from_spec(MyModels.CLAUDE_OPUS_4_7_DATED, user_prompt="...")
      MyModels.all()       # built-ins + custom entries
      MyModels.by_id("claude_opus_4_7_20260416")

Field semantics
===============

- ``id`` — stable internal slug, persisted to the DB as a column. Pick
  something durable; this is the analytics key. Convention: lower-snake-case
  mirroring the api_id.
- ``api_id`` — exact string the provider expects on the wire. This is what
  goes into the HTTP request to Anthropic / OpenAI / Gemini.
- ``name`` — human-readable label. Free-form.
- ``provider`` — drives request dispatch. Required.
- ``input_token_price_usd`` / ``output_token_price_usd`` — optional. Setting
  them enables ``expected_input_cost_usd`` forecasting in ``LLMRequest`` and
  ``AgentTask``. Leave ``None`` when unknown or unstable.

Agent provider constraint
=========================

``AgentTask.from_spec`` rejects any spec whose ``provider`` is not in
``AGENT_SUPPORTED_PROVIDERS`` (currently ``{anthropic, openai}`` because no
Google agent SDK exists yet). When that changes, add ``Providers.GOOGLE`` to
the frozenset — no other code change required.

MIT License
Copyright (c) 2025 Anton Tarasenko
"""

from enum import StrEnum
from typing import (
    ClassVar,
    Final,
)

import pydantic as pyd


class Providers(StrEnum):
    """Supported model providers."""

    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENAI = "openai"


class ModelVersion(pyd.BaseModel):
    """Metadata for a single model version.

    Construct directly for custom models. See the module docstring for the
    full registration patterns and field semantics.
    """

    model_config = pyd.ConfigDict(frozen=True, protected_namespaces=())

    id: str
    api_id: str
    name: str
    provider: Providers
    input_token_price_usd: float | None = None
    output_token_price_usd: float | None = None


class Models:
    """Curated catalog of known LLM/agent models.

    Treat as a namespace of constants, not a closed set. See the module
    docstring for the three ways to add custom models (built-in / ad hoc /
    subclass).
    """

    CLAUDE_HAIKU_4_5: ClassVar[ModelVersion] = ModelVersion(
        id="claude_haiku_4_5_20251001",
        api_id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider=Providers.ANTHROPIC,
        input_token_price_usd=0.000001000,
        output_token_price_usd=0.000005000,
    )
    CLAUDE_OPUS_4_5: ClassVar[ModelVersion] = ModelVersion(
        id="claude_opus_4_5_20251101",
        api_id="claude-opus-4-5-20251101",
        name="Claude Opus 4.5",
        provider=Providers.ANTHROPIC,
        input_token_price_usd=0.000005000,
        output_token_price_usd=0.000025000,
    )
    CLAUDE_OPUS_4_6: ClassVar[ModelVersion] = ModelVersion(
        id="claude_opus_4_6",
        api_id="claude-opus-4-6",
        name="Claude Opus 4.6",
        provider=Providers.ANTHROPIC,
        input_token_price_usd=0.000005000,
        output_token_price_usd=0.000025000,
    )
    CLAUDE_OPUS_4_7: ClassVar[ModelVersion] = ModelVersion(
        id="claude_opus_4_7",
        api_id="claude-opus-4-7",
        name="Claude Opus 4.7",
        provider=Providers.ANTHROPIC,
        input_token_price_usd=0.000005000,
        output_token_price_usd=0.000025000,
    )
    CLAUDE_SONNET_4_5: ClassVar[ModelVersion] = ModelVersion(
        id="claude_sonnet_4_5_20250929",
        api_id="claude-sonnet-4-5-20250929",
        name="Claude Sonnet 4.5",
        provider=Providers.ANTHROPIC,
        input_token_price_usd=0.000003000,
        output_token_price_usd=0.000015000,
    )
    CLAUDE_SONNET_4_6: ClassVar[ModelVersion] = ModelVersion(
        id="claude_sonnet_4_6",
        api_id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider=Providers.ANTHROPIC,
        input_token_price_usd=0.000003000,
        output_token_price_usd=0.000015000,
    )
    GEMINI_2_5_FLASH: ClassVar[ModelVersion] = ModelVersion(
        id="gemini_2_5_flash",
        api_id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        provider=Providers.GOOGLE,
        input_token_price_usd=0.000000300,
        output_token_price_usd=0.000002500,
    )
    GEMINI_2_5_FLASH_LITE: ClassVar[ModelVersion] = ModelVersion(
        id="gemini_2_5_flash_lite",
        api_id="gemini-2.5-flash-lite",
        name="Gemini 2.5 Flash Lite",
        provider=Providers.GOOGLE,
        input_token_price_usd=0.000000100,
        output_token_price_usd=0.000000400,
    )
    GEMINI_2_5_PRO: ClassVar[ModelVersion] = ModelVersion(
        id="gemini_2_5_pro",
        api_id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        provider=Providers.GOOGLE,
        input_token_price_usd=0.000001250,
        output_token_price_usd=0.000010000,
    )
    GEMINI_3_1_FLASH_LITE: ClassVar[ModelVersion] = ModelVersion(
        id="gemini_3_1_flash_lite",
        api_id="gemini-3.1-flash-lite",
        name="Gemini 3.1 Flash Lite",
        provider=Providers.GOOGLE,
        input_token_price_usd=0.000000250,
        output_token_price_usd=0.000001500,
    )
    GEMINI_3_1_PRO: ClassVar[ModelVersion] = ModelVersion(
        id="gemini_3_1_pro_preview",
        api_id="gemini-3.1-pro-preview",
        name="Gemini 3.1 Pro",
        provider=Providers.GOOGLE,
        input_token_price_usd=0.000002000,
        output_token_price_usd=0.000012000,
    )
    GEMINI_3_FLASH: ClassVar[ModelVersion] = ModelVersion(
        id="gemini_3_flash",
        api_id="gemini-3-flash",
        name="Gemini 3 Flash",
        provider=Providers.GOOGLE,
        input_token_price_usd=0.000000500,
        output_token_price_usd=0.000003000,
    )
    GPT_5: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5",
        api_id="gpt-5",
        name="GPT-5",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000001250,
        output_token_price_usd=0.000010000,
    )
    GPT_5_2: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_2",
        api_id="gpt-5.2",
        name="GPT-5.2",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000001750,
        output_token_price_usd=0.000014000,
    )
    GPT_5_4: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_4",
        api_id="gpt-5.4",
        name="GPT-5.4",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000002500,
        output_token_price_usd=0.000015000,
    )
    GPT_5_4_MINI: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_4_mini",
        api_id="gpt-5.4-mini",
        name="GPT-5.4 Mini",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000000750,
        output_token_price_usd=0.000004500,
    )
    GPT_5_5: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_5",
        api_id="gpt-5.5",
        name="GPT-5.5",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000005000,
        output_token_price_usd=0.000030000,
    )
    GPT_5_5_PRO: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_5_pro",
        api_id="gpt-5.5-pro",
        name="GPT-5.5 Pro",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000030000,
        output_token_price_usd=0.000180000,
    )
    GPT_5_MINI: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_mini",
        api_id="gpt-5-mini",
        name="GPT-5 Mini",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000000250,
        output_token_price_usd=0.000002000,
    )
    GPT_5_NANO: ClassVar[ModelVersion] = ModelVersion(
        id="gpt_5_nano",
        api_id="gpt-5-nano",
        name="GPT-5 Nano",
        provider=Providers.OPENAI,
        input_token_price_usd=0.000000050,
        output_token_price_usd=0.000000400,
    )

    @classmethod
    def all(cls) -> list[ModelVersion]:
        """Return every ``ModelVersion`` declared on ``cls`` (including inherited)."""
        seen: set[str] = set()
        result: list[ModelVersion] = []
        for klass in cls.__mro__:
            for key, value in vars(klass).items():
                if key.startswith("_") or key in seen:
                    continue
                if isinstance(value, ModelVersion):
                    seen.add(key)
                    result.append(value)
        return result

    @classmethod
    def by_id(cls, id_: str) -> ModelVersion:
        """Resolve a ``ModelVersion`` by its ``id`` field.

        :param id_: The ``ModelVersion.id`` to look up.
        :type id_: str
        :returns: The matching ``ModelVersion``.
        :rtype: ModelVersion
        :raises ValueError: If no entry has the given id.
        """
        for spec in cls.all():
            if spec.id == id_:
                return spec
        msg = f"Unknown model id: {id_}"
        raise ValueError(msg)


AGENT_SUPPORTED_PROVIDERS: Final[frozenset[Providers]] = frozenset({
    Providers.ANTHROPIC,
    Providers.OPENAI,
})
"""Providers whose models can drive an ``AgentTask``.

Today this excludes Google because neither ``claude-agent-sdk`` nor
``openai-agents`` has a Google equivalent. Add ``Providers.GOOGLE`` once an
agent SDK supports it.
"""

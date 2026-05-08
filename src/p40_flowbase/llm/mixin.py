"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
import json
import pathlib
import uuid
from datetime import (
    UTC,
    datetime,
)
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    override,
)

import pydantic as pyd

from p40_flowbase.http.mixin import HTTPDB
from p40_flowbase.http.models import (
    HTTPRequest,
    HTTPRequestGroup,
)
from p40_flowbase.llm.models import (
    LLMFile,
    LLMRequest,
)
from p40_flowbase.logging import logger
from p40_flowbase.providers import (
    ModelVersion,
    Providers,
)

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement


def _ensure_additional_properties_false(schema: Any) -> Any:
    """Recursively set additionalProperties=false on every object-type schema.

    Required by providers like Anthropic and OpenAI (strict mode) for
    structured output schemas. Accepts ``Any`` because schemas may contain
    nested non-dict values (lists, primitives) reached via recursion.
    """
    if not isinstance(schema, dict):
        return schema

    if schema.get("type") == "object" and "properties" in schema:
        schema["additionalProperties"] = False
        for prop_schema in schema["properties"].values():
            _ensure_additional_properties_false(prop_schema)

    for key in ("$defs", "definitions"):
        if key in schema:
            for def_schema in schema[key].values():
                _ensure_additional_properties_false(def_schema)

    if "items" in schema:
        _ensure_additional_properties_false(schema["items"])

    for key in ("anyOf", "allOf", "oneOf"):
        if key in schema:
            for sub_schema in schema[key]:
                _ensure_additional_properties_false(sub_schema)

    return schema


class LLMDB(HTTPDB):
    """DB for executing LLM requests via HTTP.

    Inherits from ``HTTPDB`` so LLM requests are logged into the same
    ``HTTPRequest`` table alongside raw HTTP calls. Subclasses should set
    ``tables`` to include at least ``LLMRequestGroup`` / ``LLMRequestExtra``
    / ``LLMFile`` / ``LLMRequest`` plus the HTTP tables, and implement
    ``_populate_llm_requests() -> uuid.UUID``.

    Configure API keys via ``LLMDB.set_api_keys(...)`` before execution.
    """

    rate_limit: ClassVar[float] = 1.0
    rate_period: ClassVar[float] = 1.0

    _request_model: ClassVar[type[Any] | None] = LLMRequest
    _pending_column: ClassVar[str | None] = "requested_at_utc"

    @classmethod
    @override
    def _failed_predicate(cls) -> "ColumnElement[bool] | None":
        from sqlalchemy import and_

        return and_(
            LLMRequest.requested_at_utc.is_not(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            LLMRequest.response_text.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            LLMRequest.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        )

    _anthropic_api_key: ClassVar[str | None] = None
    _google_api_key: ClassVar[str | None] = None
    _openai_api_key: ClassVar[str | None] = None

    @classmethod
    def set_api_keys(
        cls,
        anthropic_api_key: str | None = None,
        google_api_key: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        """Set API keys for LLM providers."""
        cls._anthropic_api_key = anthropic_api_key
        cls._google_api_key = google_api_key
        cls._openai_api_key = openai_api_key

    @override
    async def _populate(self) -> uuid.UUID:
        if not hasattr(self, "_populate_llm_requests"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement "
                "_populate_llm_requests() method"
            )
        result: uuid.UUID = await self._populate_llm_requests()  # pyright: ignore[reportAttributeAccessIssue]
        return result

    @override
    async def _execute_pending(  # type: ignore[override]  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
    ) -> list[LLMRequest]:
        return await self._execute_pending_llm_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            llm_request_group_id=str(group_id) if group_id else None,
        )

    @override
    async def _retry_failed(  # type: ignore[override]  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
    ) -> list[LLMRequest]:
        return await self._retry_failed_llm_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            llm_request_group_id=str(group_id) if group_id else None,
        )

    @override
    async def _get_wave_results(  # type: ignore[override]  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        group_id: uuid.UUID,
    ) -> list[LLMRequest]:
        return await self._get_llm_wave_results(group_id=group_id)

    def _model_to_json_schema(self, model_class: type[pyd.BaseModel]) -> dict[str, Any]:
        """Convert Pydantic or SQLModel model to a strict-mode JSON schema."""
        schema = model_class.model_json_schema()
        result: dict[str, Any] = _ensure_additional_properties_false(schema)
        return result

    def _build_anthropic_request(
        self,
        model: str,
        system_prompt: str | None,
        user_prompt: str | None,
        temperature: float | None,
        attachments_data: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
        effort: str | None = None,
    ) -> dict[str, Any]:
        """Build request body for Anthropic API."""
        content = []

        for attachment in attachments_data:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": attachment["media_type"],
                        "data": attachment["base64_data"],
                    },
                }
            )

        if user_prompt:
            content.append({"type": "text", "text": user_prompt})

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 8192,
            "messages": [
                {"role": "user", "content": content if content else user_prompt or ""}
            ],
        }

        if system_prompt:
            body["system"] = system_prompt

        if temperature is not None:
            body["temperature"] = temperature

        if response_schema is not None:
            body["output_format"] = {
                "type": "json_schema",
                "schema": response_schema,
            }

        if effort is not None:
            body["output_config"] = {"effort": effort}

        return body

    @staticmethod
    def _gemini_thinking_config(model: str, effort: str | None) -> dict[str, Any] | None:
        """Map an ``LLMEffort`` value to a Gemini ``thinkingConfig`` block.

        Gemini 3.x uses ``thinking_level`` (MINIMAL/LOW/MEDIUM/HIGH); Gemini 2.5
        uses ``thinking_budget`` (token integer; -1 enables dynamic budgeting).
        Returns ``None`` for non-Gemini models or when effort is unset, so the
        caller can omit the field entirely.
        """
        if effort is None:
            return None

        if model.startswith("gemini-3"):
            level_by_effort: dict[str, str] = {
                "none": "MINIMAL",
                "minimal": "MINIMAL",
                "low": "LOW",
                "medium": "MEDIUM",
                "high": "HIGH",
                "xhigh": "HIGH",
                "max": "HIGH",
            }
            level = level_by_effort.get(effort)
            if level is None:
                return None
            # Gemini 3.1 Pro does not support MINIMAL; promote to LOW.
            if "pro" in model and level == "MINIMAL":
                level = "LOW"
            return {"thinking_level": level}

        if model.startswith("gemini-2.5"):
            budget_by_effort: dict[str, int] = {
                "none": 0,
                "minimal": 128,
                "low": 1024,
                "medium": 4096,
                "high": 16384,
                "xhigh": 24576,
                "max": -1,
            }
            budget = budget_by_effort.get(effort)
            if budget is None:
                return None
            # Gemini 2.5 Pro can't disable thinking; clamp to the documented minimum.
            if "pro" in model and budget == 0:
                budget = 128
            return {"thinking_budget": budget}

        return None

    def _build_google_request(
        self,
        model: str,
        system_prompt: str | None,
        user_prompt: str | None,
        temperature: float | None,
        attachments_data: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
        effort: str | None = None,
    ) -> dict[str, Any]:
        """Build request body for Google Gemini API."""
        parts: list[dict[str, Any]] = []

        for attachment in attachments_data:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": attachment["media_type"],
                        "data": attachment["base64_data"],
                    }
                }
            )

        if user_prompt:
            parts.append({"text": user_prompt})

        body: dict[str, Any] = {
            "contents": [{"parts": parts if parts else [{"text": ""}]}],
        }

        if system_prompt:
            body["system_instruction"] = {"parts": [{"text": system_prompt}]}

        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature

        if response_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseJsonSchema"] = response_schema

        thinking_config = self._gemini_thinking_config(model=model, effort=effort)
        if thinking_config is not None:
            generation_config["thinkingConfig"] = thinking_config

        if generation_config:
            body["generationConfig"] = generation_config

        return body

    def _build_openai_request(
        self,
        model: str,
        system_prompt: str | None,
        user_prompt: str | None,
        temperature: float | None,
        attachments_data: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
        effort: str | None = None,
    ) -> dict[str, Any]:
        """Build request body for OpenAI API."""
        messages: list[dict[str, Any]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        user_content: list[dict[str, Any]] = []

        for attachment in attachments_data:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{attachment['media_type']};base64,{attachment['base64_data']}"
                    },
                }
            )

        if user_prompt:
            user_content.append({"type": "text", "text": user_prompt})

        if user_content:
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": ""})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if temperature is not None:
            body["temperature"] = temperature

        if response_schema is not None:
            schema_name = response_schema.get("title", "response")
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            }

        if effort is not None:
            body["reasoning_effort"] = effort

        return body

    def _parse_anthropic_response(self, response_body_text: str) -> str:
        """Parse response text from Anthropic API response."""
        data: dict[str, Any] = json.loads(response_body_text)
        content = data.get("content", [])
        text_parts = [
            block.get("text", "") for block in content if block.get("type") == "text"
        ]
        return "".join(text_parts)

    def _parse_google_response(self, response_body_text: str) -> str:
        """Parse response text from Google Gemini API response."""
        data: dict[str, Any] = json.loads(response_body_text)
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text_parts = [part.get("text", "") for part in parts if "text" in part]
        return "".join(text_parts)

    def _parse_openai_response(self, response_body_text: str) -> str:
        """Parse response text from OpenAI API response."""
        data: dict[str, Any] = json.loads(response_body_text)
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        text: str = message.get("content", "")
        return text

    def _get_media_type(self, filename: str) -> str:
        """Return MIME type from filename extension."""
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        media_types = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "pdf": "application/pdf",
            "txt": "text/plain",
            "json": "application/json",
            "csv": "text/csv",
        }
        return media_types.get(ext, "application/octet-stream")

    async def _add_llm_requests(
        self,
        requests: list[dict[str, Any]],
    ) -> list[LLMRequest]:
        """Insert LLM request rows for later execution."""
        created_requests = []

        async with self.session_factory() as session:
            for request_data in requests:
                attachments = request_data.get("attachments")
                attachments_json = None
                if attachments:
                    normalized_attachments: list[str] = []
                    for file_id in attachments:
                        if isinstance(file_id, uuid.UUID):
                            normalized_attachments.append(file_id.hex)
                        else:
                            normalized_attachments.append(
                                str(file_id).replace("-", "").lower()
                            )
                    attachments_json = json.dumps(normalized_attachments)

                response_schema_json = None
                response_schema_input = request_data.get("response_schema")
                if response_schema_input is not None:
                    if isinstance(response_schema_input, dict):
                        schema_dict = response_schema_input
                    elif isinstance(response_schema_input, type):
                        schema_dict = self._model_to_json_schema(response_schema_input)
                    else:
                        raise ValueError(
                            f"response_schema must be a Pydantic/SQLModel class or a dict, "
                            f"got {type(response_schema_input)}"
                        )
                    _ensure_additional_properties_false(schema_dict)
                    response_schema_json = json.dumps(schema_dict)

                llm_request = LLMRequest.from_spec(
                    request_data["model"],
                    system_prompt=request_data.get("system_prompt"),
                    user_prompt=request_data.get("user_prompt"),
                    temperature=request_data.get("temperature"),
                    effort=request_data.get("effort"),
                    attachments=attachments_json,
                    response_schema=response_schema_json,
                    llm_request_group_id=request_data.get("llm_request_group_id"),
                    llm_request_extra_id=request_data.get("llm_request_extra_id"),
                )
                session.add(llm_request)
                created_requests.append(llm_request)

            await session.commit()

            for llm_request in created_requests:
                await session.refresh(llm_request)

        return created_requests

    async def _add_llm_file(
        self,
        file_path: pathlib.Path,
        data_object_class_name: str,
        data_object_id: str,
        data_object_version: str,
        data_object_format: str,
    ) -> LLMFile:
        """Insert a file row into the llm_files table."""
        import hashlib

        file_data = await asyncio.to_thread(file_path.read_bytes)
        md5sum = hashlib.md5(file_data, usedforsecurity=False).hexdigest()

        object_stem = f"{data_object_id}-{data_object_version}"
        local_dir = pathlib.Path(self.local_data) / object_stem
        format_path = local_dir / f"{object_stem}.{data_object_format}"

        if file_path == format_path:
            relative_path = "."
        else:
            relative_path = str(file_path.relative_to(local_dir))

        llm_file = LLMFile(
            name=file_path.name,
            md5sum=md5sum,
            size_bytes=len(file_data),
            data_object_class_name=data_object_class_name,
            data_object_id=data_object_id,
            data_object_version=data_object_version,
            data_object_format=data_object_format,
            local_tmp_path=relative_path,
        )

        async with self.session_factory() as session:
            session.add(llm_file)
            await session.commit()
            await session.refresh(llm_file)

        return llm_file

    async def _load_attachment_data(
        self,
        llm_request: LLMRequest,
    ) -> list[dict[str, str]]:
        """Load and base64-encode attachments for an LLM request."""
        import base64

        from sqlmodel import select

        attachments_data: list[dict[str, str]] = []
        if not llm_request.attachments:
            return attachments_data

        attachment_ids = json.loads(llm_request.attachments)
        for file_id in attachment_ids:
            file_uuid = uuid.UUID(file_id) if isinstance(file_id, str) else file_id
            async with self.session_factory() as session:
                file_statement = select(LLMFile).where(
                    LLMFile.llm_file_id == file_uuid
                )
                file_result = await session.exec(file_statement)
                llm_file = file_result.first()

            if not llm_file:
                logger.warning(
                    f"LLM file record not found for ID {file_id}, "
                    f"skipping attachment for request {llm_request.llm_request_id}"
                )
                continue

            object_stem = (
                f"{llm_file.data_object_id}-{llm_file.data_object_version}"
            )
            local_dir = pathlib.Path(self.local_data) / object_stem
            format_path = local_dir / f"{object_stem}.{llm_file.data_object_format}"

            if llm_file.local_tmp_path == ".":
                file_path = format_path
            else:
                file_path = local_dir / llm_file.local_tmp_path

            if file_path.exists():
                file_data = await asyncio.to_thread(file_path.read_bytes)
                attachments_data.append(
                    {
                        "base64_data": base64.b64encode(file_data).decode(),
                        "media_type": self._get_media_type(llm_file.name),
                        "name": llm_file.name,
                    }
                )
            else:
                logger.warning(
                    f"Attachment file not found at {file_path} "
                    f"for LLM file {llm_file.llm_file_id}, "
                    f"skipping attachment for request {llm_request.llm_request_id}"
                )

        return attachments_data

    def _prepare_llm_http_request(
        self,
        llm_request: LLMRequest,
        attachments_data: list[dict[str, str]],
        ephemeral_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str], dict[str, str], dict[str, Any]]:
        """Prepare provider-specific URL, headers, and body for an LLM request."""
        llm_model = llm_request.model
        provider = llm_model.provider

        response_schema = None
        if llm_request.response_schema:
            response_schema = json.loads(llm_request.response_schema)

        if provider == Providers.ANTHROPIC:
            api_url = "https://api.anthropic.com/v1/messages"
            request_body = self._build_anthropic_request(
                model=llm_model.api_id,
                system_prompt=llm_request.system_prompt,
                user_prompt=llm_request.user_prompt,
                temperature=llm_request.temperature,
                attachments_data=attachments_data,
                response_schema=response_schema,
                effort=llm_request.effort,
            )
            stored_headers = {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            if response_schema is not None:
                stored_headers["anthropic-beta"] = "structured-outputs-2025-11-13"
            api_key_headers = {}
            if self._anthropic_api_key:
                api_key_headers["x-api-key"] = self._anthropic_api_key
            if ephemeral_headers:
                api_key_headers.update(ephemeral_headers)

        elif provider == Providers.GOOGLE:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{llm_model.api_id}:generateContent"
            request_body = self._build_google_request(
                model=llm_model.api_id,
                system_prompt=llm_request.system_prompt,
                user_prompt=llm_request.user_prompt,
                temperature=llm_request.temperature,
                attachments_data=attachments_data,
                response_schema=response_schema,
                effort=llm_request.effort,
            )
            stored_headers = {"Content-Type": "application/json"}
            api_key_headers = {}
            if self._google_api_key:
                api_key_headers["x-goog-api-key"] = self._google_api_key
            if ephemeral_headers:
                api_key_headers.update(ephemeral_headers)

        elif provider == Providers.OPENAI:
            api_url = "https://api.openai.com/v1/chat/completions"
            request_body = self._build_openai_request(
                model=llm_model.api_id,
                system_prompt=llm_request.system_prompt,
                user_prompt=llm_request.user_prompt,
                temperature=llm_request.temperature,
                attachments_data=attachments_data,
                response_schema=response_schema,
                effort=llm_request.effort,
            )
            stored_headers = {"Content-Type": "application/json"}
            api_key_headers = {}
            if self._openai_api_key:
                api_key_headers["Authorization"] = f"Bearer {self._openai_api_key}"
            if ephemeral_headers:
                api_key_headers.update(ephemeral_headers)

        else:
            raise ValueError(f"Unknown provider: {provider}")

        return api_url, stored_headers, api_key_headers, request_body

    def _parse_llm_response(
        self,
        http_request: HTTPRequest,
        model: ModelVersion,
    ) -> str | None:
        """Parse provider response from the underlying ``HTTPRequest`` row."""
        if not http_request.response_body_text:
            logger.warning(
                f"LLM request failed: No response body "
                f"(http_request_id: {http_request.http_request_id})"
            )
            return None

        if http_request.response_status == 200:
            provider = model.provider
            if provider == Providers.ANTHROPIC:
                return self._parse_anthropic_response(http_request.response_body_text)
            if provider == Providers.GOOGLE:
                return self._parse_google_response(http_request.response_body_text)
            if provider == Providers.OPENAI:
                return self._parse_openai_response(http_request.response_body_text)
        else:
            logger.error(
                f"LLM request failed with status {http_request.response_status} "
                f"(http_request_id: {http_request.http_request_id}). "
                f"Response body: {http_request.response_body_text}"
            )

        return None

    async def _process_single_llm_request(
        self,
        http_client: Any,
        llm_request: LLMRequest,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> LLMRequest:
        """Execute a single LLM request via its underlying HTTP call."""
        attachments_data = await self._load_attachment_data(llm_request)

        (
            api_url,
            stored_headers,
            api_key_headers,
            request_body,
        ) = self._prepare_llm_http_request(
            llm_request,
            attachments_data,
            ephemeral_headers,
        )

        http_request_group_class = HTTPRequestGroup
        for table_class in self.tables:
            if (
                hasattr(table_class, "__tablename__")
                and table_class.__tablename__ == "http_request_groups"
                and table_class != HTTPRequestGroup
            ):
                http_request_group_class = table_class
                break

        if http_request_group_class == HTTPRequestGroup:
            http_request_group = HTTPRequestGroup()
        else:
            http_request_group = http_request_group_class(
                created_by_class="LLMDB"  # pyright: ignore[reportCallIssue]
            )

        async with self.session_factory() as session:
            session.add(http_request_group)
            await session.commit()
            await session.refresh(http_request_group)

        http_requests = await self._add_http_requests(
            [
                {
                    "request_url": api_url,
                    "request_method": "POST",
                    "request_headers": json.dumps(stored_headers),
                    "request_body": json.dumps(request_body),
                    "http_request_group_id": http_request_group.http_request_group_id,
                }
            ]
        )

        http_request = http_requests[0]

        http_request = await self._process_single_http_request(
            http_client,
            http_request,
            api_key_headers,
        )

        async with self.session_factory() as session:
            llm_request.http_request_id = http_request.http_request_id
            session.add(llm_request)
            await session.commit()

        response_text = self._parse_llm_response(http_request, llm_request.model)

        async with self.session_factory() as session:
            llm_request.response_text = response_text
            llm_request.requested_at_utc = datetime.now(UTC)
            session.add(llm_request)
            await session.commit()
            await session.refresh(llm_request)

        return llm_request

    async def _execute_pending_llm_requests(
        self,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
        llm_request_group_id: str | None = None,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> list[LLMRequest]:
        """Execute all LLM requests where ``requested_at_utc`` is null."""
        import aiohttp
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(LLMRequest).where(
                LLMRequest.requested_at_utc.is_(None)  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            if llm_request_group_id is not None:
                group_uuid = uuid.UUID(llm_request_group_id)
                statement = statement.where(
                    LLMRequest.llm_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            llm_requests = result.all()

        async with aiohttp.ClientSession() as http_client:
            async def execute_one(llm_request: LLMRequest) -> LLMRequest:
                return await self._process_single_llm_request(
                    http_client,
                    llm_request,
                    ephemeral_headers,
                )

            return await self._run_batch(
                rows=list(llm_requests),
                execute_one=execute_one,
                rate_limit=rate_limit,
                rate_period=rate_period,
                is_success=lambda r: r.response_text is not None,
                label="LLM request",
            )

    async def _retry_failed_llm_requests(
        self,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
        llm_request_group_id: str | None = None,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> list[LLMRequest]:
        """Retry LLM requests that failed.

        Creates fresh ``LLMRequest`` rows for each failed request (marking
        the originals as superseded) and executes them in a second pass.
        """
        import sqlalchemy
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(LLMRequest).where(
                LLMRequest.requested_at_utc.is_not(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
                LLMRequest.response_text.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
                LLMRequest.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            if llm_request_group_id is not None:
                group_uuid = uuid.UUID(llm_request_group_id)
                statement = statement.where(
                    LLMRequest.llm_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            failed_requests = result.all()

        retry_requests_data = []
        for failed_request in failed_requests:
            retry_data = {
                "model": failed_request.model,
                "system_prompt": failed_request.system_prompt,
                "user_prompt": failed_request.user_prompt,
                "temperature": failed_request.temperature,
                "attachments": (
                    json.loads(failed_request.attachments)
                    if failed_request.attachments
                    else None
                ),
                "llm_request_group_id": failed_request.llm_request_group_id,
                "llm_request_extra_id": failed_request.llm_request_extra_id,
            }
            if failed_request.response_schema:
                retry_data["response_schema"] = json.loads(
                    failed_request.response_schema
                )
            retry_requests_data.append(retry_data)

        new_requests = await self._add_llm_requests(retry_requests_data)

        async with self.session_factory() as session:
            for failed_request, new_request in zip(failed_requests, new_requests, strict=True):
                await session.exec(
                    sqlalchemy.update(LLMRequest)
                    .where(
                        LLMRequest.llm_request_id  # type: ignore[arg-type]
                        == failed_request.llm_request_id  # pyright: ignore[reportArgumentType]
                    )
                    .values(superseded_by_id=new_request.llm_request_id)
                )
            await session.commit()

        return await self._execute_pending_llm_requests(
            rate_limit=rate_limit,
            rate_period=rate_period,
            llm_request_group_id=llm_request_group_id,
            ephemeral_headers=ephemeral_headers,
        )

    async def _get_llm_wave_results(
        self,
        group_id: uuid.UUID,
    ) -> list[LLMRequest]:
        """Return non-superseded LLM requests for ``group_id``."""
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(LLMRequest).where(
                LLMRequest.llm_request_group_id == group_id,
                LLMRequest.superseded_by_id.is_(None),  # type: ignore[union-attr]  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            )
            result = await session.exec(statement)
            return list(result.all())

"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
import json
import pathlib
import time
import uuid
from collections.abc import Callable
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Any,
)

import pydantic as pyd

from p40_flowbase.http.models import (
    HTTPRequest,
    HTTPRequestGroup,
)
from p40_flowbase.llm.models import (
    LLMFile,
    LLMRequest,
)
from p40_flowbase.llm.providers import (
    LLMModels,
    LLMModelVersion,
    LLMProviders,
)
from p40_flowbase.logging import logger


def _ensure_additional_properties_false(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively set additionalProperties to false on all object-type schemas.

    Required by providers like Anthropic and OpenAI (strict mode) for structured
    output schemas.

    Args:
        schema: JSON schema dict (modified in place and returned).

    Returns:
        The same schema dict with additionalProperties set.
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


class LLMRequestsDBMixin:
    """Mixin for executing LLM requests via HTTP.

    Classes using this mixin must include LLMRequestGroup, LLMRequestExtra,
    LLMFile, LLMRequest, and HTTP-related models in their schema attribute.
    The class must also inherit from HTTPRequestsDBMixin.

    Subclasses should implement:
        - async def _populate_llm_requests(self) -> uuid.UUID:
            Create and add LLM requests, return the group_id.

    Configuration:
        Set API keys via the config module:
        - config.settings.anthropic_api_key
        - config.settings.google_api_key
        - config.settings.openai_api_key
    """

    default_rate_limit: float = 1.0
    default_rate_period: float = 1.0

    # API keys - should be set by project config
    _anthropic_api_key: str | None = None
    _google_api_key: str | None = None
    _openai_api_key: str | None = None

    @classmethod
    def set_api_keys(
        cls,
        anthropic_api_key: str | None = None,
        google_api_key: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        """Set API keys for LLM providers.

        Args:
            anthropic_api_key: Anthropic API key.
            google_api_key: Google API key.
            openai_api_key: OpenAI API key.
        """
        cls._anthropic_api_key = anthropic_api_key
        cls._google_api_key = google_api_key
        cls._openai_api_key = openai_api_key

    async def populate(self) -> uuid.UUID:
        """Populate LLM requests based on object version and configuration.

        Returns:
            UUID of the created request group.
        """
        if not hasattr(self, "_populate_llm_requests"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement _populate_llm_requests() method"
            )
        return await self._populate_llm_requests()

    async def execute(
        self,
        group_id: uuid.UUID | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
    ):
        """Execute pending LLM requests.

        Args:
            group_id: If provided, only execute requests from this group.
            rate_limit: Maximum requests per rate_period. Defaults to self.default_rate_limit.
            rate_period: Time period in seconds for rate limiting. Defaults to self.default_rate_period.

        Returns:
            List of executed LLM request entries.
        """
        return await self._execute_pending_llm_requests(
            rate_limit=rate_limit if rate_limit is not None else self.default_rate_limit,
            rate_period=rate_period if rate_period is not None else self.default_rate_period,
            llm_request_group_id=str(group_id) if group_id else None,
        )

    async def retry(
        self,
        group_id: uuid.UUID | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
    ):
        """Retry failed LLM requests.

        Args:
            group_id: If provided, only retry requests from this group.
            rate_limit: Maximum requests per rate_period. Defaults to self.default_rate_limit.
            rate_period: Time period in seconds for rate limiting. Defaults to self.default_rate_period.

        Returns:
            List of retried LLM request entries.
        """
        return await self._retry_failed_llm_requests(
            rate_limit=rate_limit if rate_limit is not None else self.default_rate_limit,
            rate_period=rate_period if rate_period is not None else self.default_rate_period,
            llm_request_group_id=str(group_id) if group_id else None,
        )

    def _model_to_json_schema(self, model_class: type[pyd.BaseModel]) -> dict[str, Any]:
        """Convert Pydantic or SQLModel model to JSON schema.

        Args:
            model_class: Pydantic BaseModel or SQLModel class

        Returns:
            JSON schema dict
        """
        schema = model_class.model_json_schema()
        return _ensure_additional_properties_false(schema)

    def _get_llm_model(self, model_id: str) -> LLMModelVersion:
        """Get LLM model metadata by model ID.

        Args:
            model_id: The model identifier (e.g., "gemini_2_5_flash_lite").

        Returns:
            LLMModelVersion metadata for the model.

        Raises:
            ValueError: If model_id is not found.
        """
        for model_enum in LLMModels:
            if model_enum.value.id == model_id:
                return model_enum.value
        raise ValueError(
            f"Unknown model '{model_id}'. Supported models: {[m.value.id for m in LLMModels]}"
        )

    def _get_provider_for_model(self, model: str) -> LLMProviders:
        """Get the provider for a given model."""
        return self._get_llm_model(model).provider

    def _build_anthropic_request(
        self,
        model: str,
        system_prompt: str | None,
        user_prompt: str | None,
        temperature: float | None,
        attachments_data: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
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

        body = {
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

        return body

    def _build_google_request(
        self,
        model: str,
        system_prompt: str | None,
        user_prompt: str | None,
        temperature: float | None,
        attachments_data: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build request body for Google Gemini API."""
        parts = []

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

        generation_config = {}
        if temperature is not None:
            generation_config["temperature"] = temperature

        if response_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseJsonSchema"] = response_schema

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
    ) -> dict[str, Any]:
        """Build request body for OpenAI API."""
        messages = []

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

        return body

    def _parse_anthropic_response(self, response_body_text: str) -> str:
        """Parse response text from Anthropic API response."""
        data = json.loads(response_body_text)
        content = data.get("content", [])
        text_parts = [
            block.get("text", "") for block in content if block.get("type") == "text"
        ]
        return "".join(text_parts)

    def _parse_google_response(self, response_body_text: str) -> str:
        """Parse response text from Google Gemini API response."""
        data = json.loads(response_body_text)
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text_parts = [part.get("text", "") for part in parts if "text" in part]
        return "".join(text_parts)

    def _parse_openai_response(self, response_body_text: str) -> str:
        """Parse response text from OpenAI API response."""
        data = json.loads(response_body_text)
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return message.get("content", "")

    def _get_media_type(self, filename: str) -> str:
        """Get MIME type from filename."""
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
        """Add LLM requests to the database for later execution.

        Args:
            requests: List of dicts with request fields. Each dict should contain:
                - model (LLMModels): LLM model enum
                - system_prompt (Optional[str]): System prompt
                - user_prompt (Optional[str]): User prompt
                - temperature (Optional[float]): Temperature setting
                - attachments (Optional[List[str]]): List of llm_file_ids
                - response_schema (Optional[Type[pyd.BaseModel] | dict]): Schema
                - llm_request_group_id (Optional[uuid.UUID]): Reference to group
                - llm_request_extra_id (Optional[uuid.UUID]): Reference to extra

        Returns:
            List of created LLMRequest entries.
        """
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

                llm_request = LLMRequest(
                    model=request_data["model"],
                    system_prompt=request_data.get("system_prompt"),
                    user_prompt=request_data.get("user_prompt"),
                    temperature=request_data.get("temperature"),
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
        """Add a file to the llm_files table.

        Args:
            file_path: Path to the file.
            data_object_class_name: Name of the data object class.
            data_object_id: ID of the data object.
            data_object_version: Version of the data object.
            data_object_format: Format of the data object.

        Returns:
            Created LLMFile entry.
        """
        import hashlib

        with open(file_path, "rb") as f:
            file_data = f.read()
            md5sum = hashlib.md5(file_data).hexdigest()

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
        """Load and encode attachment files for an LLM request.

        Args:
            llm_request: LLM request with attachments field.

        Returns:
            List of dicts with base64_data, media_type, and name.
        """
        import base64

        from sqlmodel import select

        attachments_data = []
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
                with open(file_path, "rb") as f:
                    file_data = f.read()
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
        """Prepare HTTP request for LLM API call.

        Args:
            llm_request: LLM request to prepare.
            attachments_data: Loaded attachment data.
            ephemeral_headers: Additional headers not stored in database.

        Returns:
            Tuple of (api_url, stored_headers, ephemeral_headers, request_body).
        """
        llm_model = llm_request.model.value
        provider = llm_model.provider

        response_schema = None
        if llm_request.response_schema:
            response_schema = json.loads(llm_request.response_schema)

        if provider == LLMProviders.ANTHROPIC:
            api_url = "https://api.anthropic.com/v1/messages"
            request_body = self._build_anthropic_request(
                model=llm_model.api_id,
                system_prompt=llm_request.system_prompt,
                user_prompt=llm_request.user_prompt,
                temperature=llm_request.temperature,
                attachments_data=attachments_data,
                response_schema=response_schema,
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

        elif provider == LLMProviders.GOOGLE:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{llm_model.api_id}:generateContent"
            request_body = self._build_google_request(
                model=llm_model.api_id,
                system_prompt=llm_request.system_prompt,
                user_prompt=llm_request.user_prompt,
                temperature=llm_request.temperature,
                attachments_data=attachments_data,
                response_schema=response_schema,
            )
            stored_headers = {"Content-Type": "application/json"}
            api_key_headers = {}
            if self._google_api_key:
                api_key_headers["x-goog-api-key"] = self._google_api_key
            if ephemeral_headers:
                api_key_headers.update(ephemeral_headers)

        elif provider == LLMProviders.OPENAI:
            api_url = "https://api.openai.com/v1/chat/completions"
            request_body = self._build_openai_request(
                model=llm_model.api_id,
                system_prompt=llm_request.system_prompt,
                user_prompt=llm_request.user_prompt,
                temperature=llm_request.temperature,
                attachments_data=attachments_data,
                response_schema=response_schema,
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
        model: LLMModels,
    ) -> str | None:
        """Parse LLM response from HTTP request.

        Args:
            http_request: HTTP request with response body.
            model: LLM model enum to determine provider.

        Returns:
            Parsed response text if status is 200, None otherwise.
        """
        if not http_request or not http_request.response_body_text:
            logger.warning(
                f"LLM request failed: No HTTP request or response body "
                f"(http_request_id: {http_request.http_request_id if http_request else 'None'})"
            )
            return None

        if http_request.response_status == 200:
            provider = model.value.provider
            if provider == LLMProviders.ANTHROPIC:
                return self._parse_anthropic_response(http_request.response_body_text)
            elif provider == LLMProviders.GOOGLE:
                return self._parse_google_response(http_request.response_body_text)
            elif provider == LLMProviders.OPENAI:
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
        http_client,
        llm_request: LLMRequest,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> LLMRequest:
        """Process a single LLM request.

        Args:
            http_client: aiohttp ClientSession instance.
            llm_request: LLM request to process.
            ephemeral_headers: Additional headers not stored in database.

        Returns:
            LLM request with response populated.
        """
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
        for schema_class in self.schema:
            if (
                hasattr(schema_class, "__tablename__")
                and schema_class.__tablename__ == "http_request_groups"
                and schema_class != HTTPRequestGroup
            ):
                http_request_group_class = schema_class
                break

        if http_request_group_class == HTTPRequestGroup:
            http_request_group = HTTPRequestGroup()
        else:
            http_request_group = http_request_group_class(
                created_by_class="LLMRequestsDBMixin"
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
        """Execute all LLM requests where requested_at_utc is null.

        Args:
            rate_limit: Maximum number of requests per rate_period.
            rate_period: Time period in seconds for rate limiting.
            llm_request_group_id: If provided, only process requests from this group.
            ephemeral_headers: Additional headers not stored in database.

        Returns:
            List of executed LLMRequest entries with responses populated.
        """
        import aiohttp
        from sqlmodel import select

        from p40_flowbase.helpers.rate_limit import create_limiter

        limiter = create_limiter(rate_limit, rate_period)

        async with self.session_factory() as session:
            statement = select(LLMRequest).where(LLMRequest.requested_at_utc.is_(None))
            if llm_request_group_id is not None:
                group_uuid = (
                    uuid.UUID(llm_request_group_id)
                    if isinstance(llm_request_group_id, str)
                    else llm_request_group_id
                )
                statement = statement.where(
                    LLMRequest.llm_request_group_id == group_uuid
                )
            result = await session.exec(statement)
            llm_requests = result.all()

        async with aiohttp.ClientSession() as http_client:

            async def rate_limited_request(llm_request):
                async with limiter:
                    pass
                return await self._process_single_llm_request(
                    http_client,
                    llm_request,
                    ephemeral_headers,
                )

            tasks = [rate_limited_request(req) for req in llm_requests]

            executed = []
            successful_count = 0
            failed_count = 0
            total_count = 0
            start_time = time.time()

            for completed_task in asyncio.as_completed(tasks):
                total_count += 1
                try:
                    result = await completed_task
                except Exception as e:
                    failed_count += 1
                    logger.error(f"LLM request failed with exception: {e}")
                    continue
                executed.append(result)

                if result.response_text is not None:
                    successful_count += 1
                else:
                    failed_count += 1

                if total_count % 100 == 0:
                    elapsed = time.time() - start_time
                    effective_rps = total_count / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Progress: {total_count} completed "
                        f"({successful_count} succeeded, {failed_count} failed), "
                        f"{elapsed:.1f}s elapsed, {effective_rps:.2f} RPS"
                    )

            elapsed = time.time() - start_time
            effective_rps = total_count / elapsed if elapsed > 0 else 0
            logger.info(
                f"Completed processing {total_count} LLM requests: "
                f"{successful_count} succeeded, {failed_count} failed, "
                f"{elapsed:.1f}s total, {effective_rps:.2f} RPS"
            )

        return executed

    async def _retry_failed_llm_requests(
        self,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
        llm_request_group_id: str | None = None,
        ephemeral_headers: dict[str, str] | None = None,
    ) -> list[LLMRequest]:
        """Retry LLM requests that failed.

        Creates new LLMRequest entries for each failed request and executes them.

        Args:
            rate_limit: Maximum number of requests per rate_period.
            rate_period: Time period in seconds for rate limiting.
            llm_request_group_id: If provided, only process requests from this group.
            ephemeral_headers: Additional headers not stored in database.

        Returns:
            List of new LLMRequest entries created for retries.
        """
        import sqlalchemy
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(LLMRequest).where(
                LLMRequest.requested_at_utc.is_not(None),
                LLMRequest.response_text.is_(None),
                LLMRequest.superseded_by_id.is_(None),
            )
            if llm_request_group_id is not None:
                group_uuid = (
                    uuid.UUID(llm_request_group_id)
                    if isinstance(llm_request_group_id, str)
                    else llm_request_group_id
                )
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
            for failed_request, new_request in zip(failed_requests, new_requests):
                await session.execute(
                    sqlalchemy.update(LLMRequest)
                    .where(
                        LLMRequest.llm_request_id == failed_request.llm_request_id
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
        """Get non-superseded LLM requests for a group.

        Args:
            group_id: The request group UUID.

        Returns:
            List of LLMRequest entries that have not been superseded.
        """
        from sqlmodel import select

        async with self.session_factory() as session:
            statement = select(LLMRequest).where(
                LLMRequest.llm_request_group_id == group_id,
                LLMRequest.superseded_by_id.is_(None),
            )
            result = await session.exec(statement)
            return result.all()

    async def _execute_llm_request_graph(
        self,
        lanes: list[str],
        num_steps: int,
        populate_step: Callable,
        rate_limit: float | None = None,
        rate_period: float | None = None,
        max_retries: int = 1,
        checkpointer: Any | None = None,
        thread_id: str | None = None,
    ) -> dict[str, list[list]]:
        """Execute a parallel-lane, sequential-step graph for LLM requests.

        Args:
            lanes: List of lane identifiers.
            num_steps: Number of sequential steps per lane.
            populate_step: Async callback ``(lane_id, step_index, prev_results) -> Optional[UUID]``.
            rate_limit: Maximum requests per rate_period.
            rate_period: Time period in seconds for rate limiting.
            max_retries: Maximum retry attempts per step.
            checkpointer: Optional LangGraph checkpointer.
            thread_id: Thread ID for checkpointer resumability.

        Returns:
            Dict mapping lane_id to list of step results (each a list of LLMRequest).
        """
        from p40_flowbase.orchestration.graphs import (
            build_recursive_task_graph,
        )

        effective_rate_limit = rate_limit if rate_limit is not None else self.default_rate_limit
        effective_rate_period = rate_period if rate_period is not None else self.default_rate_period

        async def execute_pending_wrapper(group_id_str: str) -> list:
            return await self._execute_pending_llm_requests(
                rate_limit=effective_rate_limit,
                rate_period=effective_rate_period,
                llm_request_group_id=group_id_str,
            )

        async def retry_failed_wrapper(group_id_str: str) -> list:
            return await self._retry_failed_llm_requests(
                rate_limit=effective_rate_limit,
                rate_period=effective_rate_period,
                llm_request_group_id=group_id_str,
            )

        async def get_wave_results_wrapper(group_id: uuid.UUID) -> list:
            return await self._get_llm_wave_results(group_id=group_id)

        graph = build_recursive_task_graph(
            populate_step=populate_step,
            execute_pending=execute_pending_wrapper,
            retry_failed=retry_failed_wrapper,
            get_wave_results=get_wave_results_wrapper,
            checkpointer=checkpointer,
        )

        config = {}
        if thread_id is not None or checkpointer is not None:
            config["configurable"] = {
                "thread_id": thread_id or uuid.uuid4().hex,
            }

        result = await graph.ainvoke(
            {
                "lanes": lanes,
                "num_steps": num_steps,
                "max_retries": max_retries,
                "lane_results": [],
            },
            config=config if config else None,
        )

        return result.get("organized_results", {})

    async def execute_graph(
        self,
        lanes: list[str],
        num_steps: int,
        populate_step: Callable | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
        max_retries: int = 1,
        checkpointer: Any | None = None,
        thread_id: str | None = None,
    ) -> dict[str, list[list]]:
        """Execute a parallel-lane, sequential-step graph for LLM requests.

        Convenience method that defaults populate_step to self._populate_lane_step.

        Args:
            lanes: List of lane identifiers.
            num_steps: Number of sequential steps per lane.
            populate_step: Async callback ``(lane_id, step_index, prev_results) -> Optional[UUID]``.
                Defaults to self._populate_lane_step if not provided.
            rate_limit: Maximum requests per rate_period.
            rate_period: Time period in seconds for rate limiting.
            max_retries: Maximum retry attempts per step.
            checkpointer: Optional LangGraph checkpointer.
            thread_id: Thread ID for checkpointer resumability.

        Returns:
            Dict mapping lane_id to list of step results (each a list of LLMRequest).
        """
        if populate_step is None:
            if not hasattr(self, "_populate_lane_step"):
                raise NotImplementedError(
                    f"{self.__class__.__name__} must implement _populate_lane_step() "
                    "or pass populate_step argument"
                )
            populate_step = self._populate_lane_step

        return await self._execute_llm_request_graph(
            lanes=lanes,
            num_steps=num_steps,
            populate_step=populate_step,
            rate_limit=rate_limit,
            rate_period=rate_period,
            max_retries=max_retries,
            checkpointer=checkpointer,
            thread_id=thread_id,
        )

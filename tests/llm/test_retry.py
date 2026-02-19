import unittest.mock
import uuid
from datetime import (
    UTC,
    datetime,
)

import pytest
from sqlmodel import select

from p40_flowbase.llm.models import LLMRequest
from p40_flowbase.llm.providers import LLMModels


class TestLLMRetry:
    @pytest.mark.asyncio
    async def test_retry_creates_new_requests_and_sets_superseded_by_id(
        self,
        llm_db,
    ):
        failed_req = LLMRequest(
            model=LLMModels.GEMINI_2_5_FLASH_LITE,
            user_prompt="test prompt",
            requested_at_utc=datetime.now(UTC),
            response_text=None,
        )
        async with llm_db.session_factory() as session:
            session.add(failed_req)
            await session.commit()
            await session.refresh(failed_req)

        original_id = failed_req.llm_request_id

        with unittest.mock.patch.object(
            type(llm_db),
            "_execute_pending_llm_requests",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            await llm_db._retry_failed_llm_requests()

        async with llm_db.session_factory() as session:
            result = await session.exec(
                select(LLMRequest).where(
                    LLMRequest.llm_request_id == original_id
                )
            )
            old_req = result.one()

        assert old_req.superseded_by_id is not None

        async with llm_db.session_factory() as session:
            result = await session.exec(
                select(LLMRequest).where(
                    LLMRequest.llm_request_id == old_req.superseded_by_id
                )
            )
            new_req = result.one()

        assert new_req.user_prompt == "test prompt"
        assert new_req.model == LLMModels.GEMINI_2_5_FLASH_LITE

    @pytest.mark.asyncio
    async def test_retry_skips_already_superseded(self, llm_db):
        already_superseded = LLMRequest(
            model=LLMModels.GEMINI_2_5_FLASH_LITE,
            user_prompt="prompt a",
            requested_at_utc=datetime.now(UTC),
            response_text=None,
            superseded_by_id=uuid.uuid4(),
        )
        not_superseded = LLMRequest(
            model=LLMModels.GEMINI_2_5_FLASH_LITE,
            user_prompt="prompt b",
            requested_at_utc=datetime.now(UTC),
            response_text=None,
        )
        async with llm_db.session_factory() as session:
            session.add(already_superseded)
            session.add(not_superseded)
            await session.commit()
            await session.refresh(already_superseded)
            await session.refresh(not_superseded)

        with unittest.mock.patch.object(
            type(llm_db),
            "_execute_pending_llm_requests",
            new=unittest.mock.AsyncMock(return_value=[]),
        ):
            await llm_db._retry_failed_llm_requests()

        async with llm_db.session_factory() as session:
            result = await session.exec(
                select(LLMRequest).where(
                    LLMRequest.llm_request_id == not_superseded.llm_request_id
                )
            )
            req = result.one()
        assert req.superseded_by_id is not None

        async with llm_db.session_factory() as session:
            result = await session.exec(
                select(LLMRequest).where(
                    LLMRequest.llm_request_id
                    == already_superseded.llm_request_id
                )
            )
            req = result.one()
        assert req.superseded_by_id == already_superseded.superseded_by_id

    @pytest.mark.asyncio
    async def test_second_retry_does_not_re_retry_originals(self, llm_db):
        failed_req = LLMRequest(
            model=LLMModels.GEMINI_2_5_FLASH_LITE,
            user_prompt="test prompt",
            requested_at_utc=datetime.now(UTC),
            response_text=None,
        )
        async with llm_db.session_factory() as session:
            session.add(failed_req)
            await session.commit()
            await session.refresh(failed_req)

        original_id = failed_req.llm_request_id

        mock_execute = unittest.mock.AsyncMock(return_value=[])

        with unittest.mock.patch.object(
            type(llm_db),
            "_execute_pending_llm_requests",
            new=mock_execute,
        ):
            await llm_db._retry_failed_llm_requests()

            async with llm_db.session_factory() as session:
                result = await session.exec(
                    select(LLMRequest).where(
                        LLMRequest.llm_request_id == original_id
                    )
                )
                old_req = result.one()
            first_superseded_by = old_req.superseded_by_id
            assert first_superseded_by is not None

            await llm_db._retry_failed_llm_requests()

        async with llm_db.session_factory() as session:
            result = await session.exec(
                select(LLMRequest).where(
                    LLMRequest.llm_request_id == original_id
                )
            )
            old_req = result.one()

        assert old_req.superseded_by_id == first_superseded_by

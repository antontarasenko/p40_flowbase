"""
MIT License

Copyright (c) 2025 Anton Tarasenko

Abstract base for request-oriented DB classes. Consolidates the public API
and orchestration that was previously triplicated across ``HTTPDB``,
``LLMDB`` and ``AgentDB``.

Subclasses implement:

    * ``_populate`` — create the request rows for this run, return group_id.
    * ``_execute_pending`` — run all rows where the per-kind "pending" filter
      matches.
    * ``_retry_failed`` — re-run rows that failed.
    * ``_get_wave_results`` — fetch non-superseded rows for a group_id.
    * ``_populate_lane_step`` — optional, used by ``execute_graph`` default.

``_run_batch`` is provided as a helper for concrete ``_execute_pending`` and
``_retry_failed`` implementations — it drives a list of rows through a
per-row coroutine under an ``aiolimiter`` semaphore and logs progress.
"""

import asyncio
import time
import uuid
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Awaitable,
    Callable,
)
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    TypeVar,
    override,
)

from p40_flowbase.core.database import DB
from p40_flowbase.logging import logger

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

TRequest = TypeVar("TRequest")


class RequestsDBMixin(DB, ABC, Generic[TRequest]):
    """Shared base for DB classes that queue + execute request-like rows.

    ``TRequest`` is the SQLModel row type (``HTTPRequest``, ``LLMRequest``,
    ``AgentTask``). Subclasses implement the five abstract hooks below; this
    class owns the public ``make`` / ``make_graph`` / ``populate`` /
    ``execute`` / ``retry`` / ``execute_graph`` API and the rate-limited
    progress loop in ``_run_batch``.
    """

    rate_limit: ClassVar[float] = 1.0
    rate_period: ClassVar[float] = 1.0

    # Subclasses set these so ``make()`` can detect work remaining in a
    # prior run (pending attempts, or non-superseded failures) and either
    # resume or skip instead of populating a new batch.
    _request_model: ClassVar[type[Any] | None] = None
    _pending_column: ClassVar[str | None] = None

    @classmethod
    def _failed_predicate(cls) -> "ColumnElement[bool] | None":
        """SQLAlchemy predicate selecting non-superseded failed rows.

        Subclasses override to enable the "already complete" skip in
        ``make()``. Returning ``None`` opts out; completion is then based
        only on the pending-column check.
        """
        return None

    async def _row_exists(self, predicate: "ColumnElement[bool] | None" = None) -> bool:
        if self._request_model is None:
            return False
        from sqlmodel import select

        statement = select(self._request_model)
        if predicate is not None:
            statement = statement.where(predicate)
        async with self.session_factory() as session:
            result = await session.exec(statement.limit(1))
            return result.first() is not None

    async def _has_any_rows(self) -> bool:
        return await self._row_exists()

    async def _has_pending_rows(self) -> bool:
        """True if any row has a null ``_pending_column`` (attempt not made)."""
        if self._request_model is None or self._pending_column is None:
            return False
        col = getattr(self._request_model, self._pending_column)
        return await self._row_exists(col.is_(None))

    async def _has_failed_rows(self) -> bool:
        """True if any non-superseded row satisfies ``_failed_predicate``."""
        predicate = self._failed_predicate()
        if predicate is None:
            return False
        return await self._row_exists(predicate)

    @override
    async def make(  # type: ignore[override]  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        replace: bool = False,
        rate_limit: float | None = None,
        rate_period: float | None = None,
        retries: int = 0,
    ) -> None:
        """Create DB, populate rows, execute them, optionally retry failures.

        ``retries`` controls how many ``retry()`` passes run after
        ``execute()``. Default ``0`` disables retries. Each pass re-drives
        non-superseded failed rows.

        Three branches when ``replace=False``:

        * **Complete** — rows exist, none pending, none failed (or
          ``retries == 0``): ``make()`` is a no-op.
        * **Resume** — pending rows, or failed rows with ``retries > 0``:
          skip ``populate``; ``execute`` / ``retry`` run unscoped
          (``group_id=None``) and drive every group to completion.
        * **Fresh** — no rows yet: populate a new group, then execute.

        With ``replace=True`` the DB is wiped and a fresh group is populated
        unconditionally.
        """
        await self.create_tables(replace=replace)

        if replace or not await self._has_any_rows():
            group_id = await self.populate()
        else:
            has_pending = await self._has_pending_rows()
            has_failed = retries > 0 and await self._has_failed_rows()
            if not has_pending and not has_failed:
                logger.info(
                    f"{self.object_stem}: already complete, skipping"
                )
                return
            logger.info(
                f"{self.object_stem}: resuming "
                f"(pending={has_pending}, failed={has_failed})"
            )
            group_id = None

        await self.execute(
            group_id=group_id,
            rate_limit=rate_limit,
            rate_period=rate_period,
        )
        for _ in range(retries):
            await self.retry(
                group_id=group_id,
                rate_limit=rate_limit,
                rate_period=rate_period,
            )

    async def make_graph(
        self,
        replace: bool = False,
        lanes: list[str] | None = None,
        num_steps: int | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
        max_retries: int = 1,
    ) -> dict[str, list[list[TRequest]]]:
        """Create DB and run parallel-lane, sequential-step graph execution."""
        await self.create_tables(replace=replace)
        return await self.execute_graph(
            lanes=lanes or [],
            num_steps=num_steps or 1,
            rate_limit=rate_limit,
            rate_period=rate_period,
            max_retries=max_retries,
        )

    async def populate(self) -> uuid.UUID:
        """Populate request rows for this run and return the group_id."""
        return await self._populate()

    async def execute(
        self,
        group_id: uuid.UUID | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
    ) -> list[TRequest]:
        """Execute pending rows (optionally scoped to ``group_id``)."""
        return await self._execute_pending(
            group_id=group_id,
            rate_limit=rate_limit if rate_limit is not None else self.rate_limit,
            rate_period=rate_period if rate_period is not None else self.rate_period,
        )

    async def retry(
        self,
        group_id: uuid.UUID | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
    ) -> list[TRequest]:
        """Retry failed rows (optionally scoped to ``group_id``)."""
        return await self._retry_failed(
            group_id=group_id,
            rate_limit=rate_limit if rate_limit is not None else self.rate_limit,
            rate_period=rate_period if rate_period is not None else self.rate_period,
        )

    async def execute_graph(
        self,
        lanes: list[str],
        num_steps: int,
        populate_step: Callable[..., Awaitable[uuid.UUID | None]] | None = None,
        rate_limit: float | None = None,
        rate_period: float | None = None,
        max_retries: int = 1,
        checkpointer: Any | None = None,
        thread_id: str | None = None,
    ) -> dict[str, list[list[TRequest]]]:
        """Run a parallel-lane, sequential-step graph over the request rows.

        If ``populate_step`` is omitted, ``self._populate_lane_step`` is used.
        """
        if populate_step is None:
            if not hasattr(self, "_populate_lane_step"):
                raise NotImplementedError(
                    f"{self.__class__.__name__} must implement _populate_lane_step() "
                    "or pass populate_step argument"
                )
            populate_step = self._populate_lane_step  # pyright: ignore[reportAttributeAccessIssue]

        from p40_flowbase.orchestration.graphs import (
            build_recursive_task_graph,
        )

        effective_rate_limit = (
            rate_limit if rate_limit is not None else self.rate_limit
        )
        effective_rate_period = (
            rate_period if rate_period is not None else self.rate_period
        )

        async def execute_pending_wrapper(group_id_str: str) -> list[TRequest]:
            group_uuid = uuid.UUID(group_id_str)
            return await self._execute_pending(
                group_id=group_uuid,
                rate_limit=effective_rate_limit,
                rate_period=effective_rate_period,
            )

        async def retry_failed_wrapper(group_id_str: str) -> list[TRequest]:
            group_uuid = uuid.UUID(group_id_str)
            return await self._retry_failed(
                group_id=group_uuid,
                rate_limit=effective_rate_limit,
                rate_period=effective_rate_period,
            )

        async def get_wave_results_wrapper(group_id: uuid.UUID) -> list[TRequest]:
            return await self._get_wave_results(group_id=group_id)

        graph = build_recursive_task_graph(
            populate_step=populate_step,  # pyright: ignore[reportArgumentType]
            execute_pending=execute_pending_wrapper,
            retry_failed=retry_failed_wrapper,
            get_wave_results=get_wave_results_wrapper,
            checkpointer=checkpointer,
        )

        config: dict[str, Any] = {}
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
            config=config if config else None,  # pyright: ignore[reportArgumentType]
        )

        organized: dict[str, list[list[TRequest]]] = result.get(
            "organized_results", {}
        )
        return organized

    async def _run_batch(
        self,
        rows: list[Any],
        *,
        execute_one: Callable[[Any], Awaitable[Any]],
        rate_limit: float,
        rate_period: float,
        is_success: Callable[[Any], bool],
        progress_every: int = 100,
        label: str = "request",
    ) -> list[Any]:
        """Drive ``rows`` through ``execute_one`` concurrently, rate-limited.

        Used by subclass ``_execute_pending`` / ``_retry_failed`` methods to
        avoid re-implementing the asyncio.as_completed + progress-logging
        loop three times.
        """
        from p40_flowbase.helpers.rate_limit import create_limiter

        limiter = create_limiter(rate_limit, rate_period)

        async def one(row: Any) -> Any:
            async with limiter:
                pass
            return await execute_one(row)

        tasks = [one(r) for r in rows]

        executed: list[Any] = []
        ok = 0
        bad = 0
        total = 0
        start = time.time()

        for future in asyncio.as_completed(tasks):
            total += 1
            try:
                result = await future
            except Exception as e:  # noqa: BLE001  # tally individual task failures without aborting the wave
                bad += 1
                logger.error(f"{label} failed with exception: {e}")
                continue
            executed.append(result)
            if is_success(result):
                ok += 1
            else:
                bad += 1
            if total % progress_every == 0:
                elapsed = time.time() - start
                rps = total / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {total} completed "
                    f"({ok} succeeded, {bad} failed), "
                    f"{elapsed:.1f}s elapsed, {rps:.2f} {label}/s"
                )

        elapsed = time.time() - start
        rps = total / elapsed if elapsed > 0 else 0
        logger.info(
            f"Completed processing {total} {label}s: "
            f"{ok} succeeded, {bad} failed, "
            f"{elapsed:.1f}s total, {rps:.2f} {label}/s"
        )
        return executed

    @abstractmethod
    async def _populate(self) -> uuid.UUID:
        """Create request rows for this run and return the group_id."""

    @abstractmethod
    async def _execute_pending(
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
    ) -> list[TRequest]:
        """Execute rows matching the per-kind 'pending' predicate."""

    @abstractmethod
    async def _retry_failed(
        self,
        group_id: uuid.UUID | str | None = None,
        rate_limit: float = 1.0,
        rate_period: float = 1.0,
    ) -> list[TRequest]:
        """Re-run rows matching the per-kind 'failed' predicate."""

    @abstractmethod
    async def _get_wave_results(
        self,
        group_id: uuid.UUID,
    ) -> list[TRequest]:
        """Return the non-superseded rows for ``group_id``."""

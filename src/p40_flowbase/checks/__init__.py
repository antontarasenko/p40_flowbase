"""Declarative post-make checks attached to ``DataObject`` subclasses.

A ``Check`` is a small object you list in a subclass's ``checks`` ClassVar;
``DataObject.make()`` and ``DataObject.amake()`` (and the request-DB
``make()`` override) iterate them after the per-object ``make_summary``
line and raise :class:`CheckFailedError` on the first failure. The
exception propagates to the caller (or Dagster, which turns the asset
red). Each check logs ``check_start`` / ``check_ok`` / ``check_failed``
lines into the per-object ``.meta.log``.

``replace=True`` does not skip checks: the data is rebuilt and revalidated.

Example::

    import p40_flowbase as fb
    from p40_flowbase import checks as ck

    class WeatherSummaryTable(fb.Table):
        checks = (ck.MinRows(1), ck.NoNulls("city"), ck.Unique("city"))

    class WeatherHTTPDB(fb.HTTPDB):
        checks = (ck.MinRequests(1), ck.MaxFailureRate(frac=0.0))

Sync vs async
-------------
Sync checks (``MinRows``, ``NoNulls``, ``Unique``, ``MinFiles``,
``NoEmptyFiles``, ``MinFileSize``, ``SchemaMatches``) override
:meth:`BaseCheck.run`. Async checks that need a DB session
(``MinRequests``, ``MaxFailureRate``) override :meth:`BaseCheck.arun`.
The lifecycle dispatcher calls ``run()`` from sync ``make()`` and
``await arun()`` from ``amake()`` / request-DB ``make()``. Attaching an
async check to a sync-only object raises ``NotImplementedError`` at
first run.
"""

from typing import (
    TYPE_CHECKING,
    Any,
    override,
)

from p40_flowbase.core.base import (
    BaseCheck,
    CheckFailedError,
)
from p40_flowbase.core.composite import Composite
from p40_flowbase.core.formats import CompositeFormat
from p40_flowbase.core.requests_mixin import RequestsDBMixin
from p40_flowbase.core.table import Table

if TYPE_CHECKING:
    import pydantic as pyd

    from p40_flowbase.core.base import DataObject


# Table checks


class MinRows(BaseCheck):
    """Fail if the table has fewer than ``n`` rows.

    Catches the most common silent error: a downstream consumer happily
    builds a 0-row parquet from an all-failed upstream, the schema
    validator passes, and Dagster shows green.
    """

    def __init__(self, n: int) -> None:
        self.n = n
        self.name = f"min_rows({n})"

    @override
    def run(self, obj: "DataObject") -> None:
        self._require(obj, Table)
        actual = obj.df.num_rows  # type: ignore[attr-defined]
        if actual < self.n:
            raise CheckFailedError(f"{self.name}: got {actual}")


class NoNulls(BaseCheck):
    """Fail if any of ``cols`` contains a null value.

    Reads ``obj.df.column(c).null_count`` for each requested column.
    Cheap (O(rows) per column).
    """

    def __init__(self, *cols: str) -> None:
        if not cols:
            raise ValueError("NoNulls requires at least one column name")
        self.cols = cols
        self.name = f"no_nulls({','.join(cols)})"

    @override
    def run(self, obj: "DataObject") -> None:
        self._require(obj, Table)
        df = obj.df  # type: ignore[attr-defined]
        offenders: list[str] = []
        for col in self.cols:
            if col not in df.column_names:
                raise CheckFailedError(
                    f"{self.name}: column '{col}' not in {df.column_names}"
                )
            if df.column(col).null_count > 0:
                offenders.append(f"{col}={df.column(col).null_count}")
        if offenders:
            raise CheckFailedError(f"{self.name}: nulls in {','.join(offenders)}")


class Unique(BaseCheck):
    """Fail if the row tuple over ``cols`` has duplicates.

    Uses ``pyarrow.compute.group_by`` for the count; comparable to a
    SQL ``GROUP BY ... HAVING COUNT(*) > 1`` in cost.
    """

    def __init__(self, *cols: str) -> None:
        if not cols:
            raise ValueError("Unique requires at least one column name")
        self.cols = cols
        self.name = f"unique({','.join(cols)})"

    @override
    def run(self, obj: "DataObject") -> None:
        import pyarrow.compute as pc

        self._require(obj, Table)
        df = obj.df  # type: ignore[attr-defined]
        for col in self.cols:
            if col not in df.column_names:
                raise CheckFailedError(
                    f"{self.name}: column '{col}' not in {df.column_names}"
                )
        sub = df.select(list(self.cols))
        grouped = sub.group_by(list(self.cols)).aggregate([([], "count_all")])
        counts = grouped.column("count_all")
        max_count = pc.max(counts).as_py() if grouped.num_rows else 0
        if max_count and max_count > 1:
            raise CheckFailedError(
                f"{self.name}: max group size = {max_count}"
            )


# Composite checks


def _composite_files(obj: "DataObject") -> list[Any]:
    """Return all regular files under the FILES directory (recursive)."""
    files_dir = obj.path_to_format(CompositeFormat.FILES)
    return [p for p in files_dir.rglob("*") if p.is_file()]


class MinFiles(BaseCheck):
    """Fail if the FILES directory holds fewer than ``n`` regular files."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.name = f"min_files({n})"

    @override
    def run(self, obj: "DataObject") -> None:
        self._require(obj, Composite)
        actual = len(_composite_files(obj))
        if actual < self.n:
            raise CheckFailedError(f"{self.name}: got {actual}")


class NoEmptyFiles(BaseCheck):
    """Fail if any file under the FILES directory is 0 bytes.

    Cheap; catches truncated downloads, half-written JSON, etc.
    """

    name = "no_empty_files"

    @override
    def run(self, obj: "DataObject") -> None:
        self._require(obj, Composite)
        offenders = [
            str(p) for p in _composite_files(obj) if p.stat().st_size == 0
        ]
        if offenders:
            raise CheckFailedError(
                f"{self.name}: {len(offenders)} empty file(s); "
                f"first={offenders[0]}"
            )


class MinFileSize(BaseCheck):
    """Fail if any file under the FILES directory is smaller than ``bytes_``.

    Use when you have a hard floor (e.g. "every JSON response should be
    at least 1 KB"). For the degenerate "no zero-byte files" case prefer
    :class:`NoEmptyFiles` for the clearer name.
    """

    def __init__(self, bytes_: int) -> None:
        self.bytes_ = bytes_
        self.name = f"min_file_size({bytes_}b)"

    @override
    def run(self, obj: "DataObject") -> None:
        self._require(obj, Composite)
        offenders = [
            (str(p), p.stat().st_size)
            for p in _composite_files(obj)
            if p.stat().st_size < self.bytes_
        ]
        if offenders:
            path, size = offenders[0]
            raise CheckFailedError(
                f"{self.name}: {len(offenders)} file(s) under floor; "
                f"first={path} ({size}b)"
            )


class SchemaMatches(BaseCheck):
    """Fail if any ``*.json`` file fails ``model.model_validate_json(...)``.

    Pydantic schema gate for ``Composite`` outputs, analogous to what
    ``Table.save_arrow`` does for parquet. Walks the FILES directory
    recursively for every file with a ``.json`` suffix.
    """

    def __init__(self, model: "type[pyd.BaseModel]") -> None:
        self.model = model
        self.name = f"schema_matches({model.__name__})"

    @override
    def run(self, obj: "DataObject") -> None:
        self._require(obj, Composite)
        for p in _composite_files(obj):
            if p.suffix.lower() != ".json":
                continue
            try:
                self.model.model_validate_json(p.read_text())
            except Exception as e:  # report the offender, then fail check
                raise CheckFailedError(
                    f"{self.name}: {p} failed validation ({type(e).__name__}: {e})"
                ) from e


# Request-DB checks


async def _count_request_rows(
    obj: "RequestsDBMixin[Any]",
    extra_predicate: Any | None = None,
) -> int:
    """Return ``COUNT(*) FROM <_request_model> WHERE superseded_by_id IS NULL``.

    The ``superseded_by_id`` predicate matches the convention used by
    each subclass's ``_summary_queries`` (HTTPDB / LLMDB / AgentDB) so
    "total" here means the same thing as in the make_summary line.
    """
    from sqlalchemy import func
    from sqlmodel import select

    model = type(obj)._request_model  # type: ignore[attr-defined]
    if model is None:
        raise CheckFailedError(
            f"{type(obj).__name__} has no _request_model set; "
            "request-DB checks need it to count rows."
        )
    statement = (
        select(func.count())
        .select_from(model)
        .where(model.superseded_by_id.is_(None))  # type: ignore[union-attr]
    )
    if extra_predicate is not None:
        statement = statement.where(extra_predicate)
    async with obj.session_factory() as session:
        result = await session.exec(statement)  # type: ignore[arg-type]
        return int(result.one() or 0)


class MinRequests(BaseCheck):
    """Fail if the request DB's main row table has fewer than ``n`` rows.

    Counts non-superseded rows from ``HTTPRequest`` / ``LLMRequest`` /
    ``AgentTask`` depending on the mixin. Catches the case where
    ``_populate_*`` produced zero work to do.
    """

    def __init__(self, n: int) -> None:
        self.n = n
        self.name = f"min_requests({n})"

    @override
    async def arun(self, obj: "DataObject") -> None:
        self._require(obj, RequestsDBMixin)
        actual = await _count_request_rows(obj)  # type: ignore[arg-type]
        if actual < self.n:
            raise CheckFailedError(f"{self.name}: got {actual}")


class MaxFailureRate(BaseCheck):
    """Fail if ``failed / total > frac`` on the request DB's main table.

    Reuses each mixin's ``_failed_predicate()`` (HTTP: ``status != 200``,
    LLM: ``response_text IS NULL``, Agent: ``is_error=True``) so the
    semantics match the failure breakdown in the ``make_summary`` line.

    ``total == 0`` short-circuits to *pass* — emptiness is the job of
    :class:`MinRequests`. Pair the two when both matter.

    :param frac: Allowed failure fraction. Required (no default) so the
        policy is always explicit at the call site.
    """

    def __init__(self, *, frac: float) -> None:
        if not 0.0 <= frac <= 1.0:
            raise ValueError(f"frac must be in [0, 1], got {frac}")
        self.frac = frac
        self.name = f"max_failure_rate({frac})"

    @override
    async def arun(self, obj: "DataObject") -> None:
        self._require(obj, RequestsDBMixin)
        total = await _count_request_rows(obj)  # type: ignore[arg-type]
        if total == 0:
            return  # MinRequests handles the empty case
        predicate = type(obj)._failed_predicate()  # type: ignore[attr-defined]
        if predicate is None:
            raise CheckFailedError(
                f"{self.name}: {type(obj).__name__} has no _failed_predicate; "
                "cannot compute failure rate."
            )
        bad = await _count_request_rows(obj, extra_predicate=predicate)  # type: ignore[arg-type]
        rate = bad / total
        if rate > self.frac:
            raise CheckFailedError(
                f"{self.name}: failed={bad} total={total} rate={rate:.3f}"
            )


# Public alias: users write ``checks: tuple[fb.Check, ...] = (...)``
Check = BaseCheck


__all__ = [
    "BaseCheck",
    "Check",
    "CheckFailedError",
    "MaxFailureRate",
    "MinFileSize",
    "MinFiles",
    "MinRequests",
    "MinRows",
    "NoEmptyFiles",
    "NoNulls",
    "SchemaMatches",
    "Unique",
]

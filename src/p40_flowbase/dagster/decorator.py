"""``@fb.asset(...)`` class decorator for registering Dagster assets.

Replaces both the legacy ``fb.asset(obj_class, ...)`` factory (now the
private ``_build_asset(...)``) and the standalone ``@fb.auto_deps``
decorator. A single decorator carries every Dagster knob a project
needs to express, plus an ``**dagster_kwargs`` escape hatch for any
``@dg.asset(...)`` argument the framework hasn't given a dedicated
parameter to.

Decorator presence is the explicit registration trigger -- a
``DataObject`` subclass without ``@fb.asset(...)`` is **not** an asset,
even if it sets ``id``. This replaces the prior ``__init_subclass__``
heuristic.

Wiring is stored on the class via the existing ``asset_*`` ClassVars
(``asset_deps``, ``asset_group``, ``asset_convert_formats``,
``asset_retries``, ``asset_convert``, ``asset_kwargs``) so
``assets_from_classes``, ``print_dag``, ``lint_asset_deps``, and
``overrides=`` continue to read from the same place.
"""

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Any, TypeVar, override

from p40_flowbase.core.base import DataObject
from p40_flowbase.dagster.lint import scan_make_for_data_object_refs
from p40_flowbase.dagster.wiring import DagsterAssetWiring


class _Auto:
    """Sentinel for ``deps=fb.AUTO`` -- AST-derive upstream classes."""

    @override
    def __repr__(self) -> str:
        return "fb.AUTO"


#: Singleton sentinel that ``@fb.asset(deps=fb.AUTO)`` recognizes; runs
#: an AST scan over the class's data-producing methods to find upstream
#: ``DataObject`` references and use them as ``asset_deps``.
AUTO = _Auto()

T = TypeVar("T", bound=type)


def asset(
    *,
    deps: Sequence[type[DataObject]] | _Auto | None = None,
    group: str | None = None,
    convert_formats: Sequence[StrEnum | str] | None = None,
    convert: bool = False,
    retries: int = 0,
    **dagster_kwargs: Any,
) -> Callable[[T], T]:
    """Register a ``DataObject`` subclass as a Dagster asset.

    All parameters are keyword-only and optional. Bare ``@fb.asset()``
    registers the class as a source asset (no upstream deps) with
    Dagster defaults for everything else.

    :param deps: Either an explicit sequence of upstream ``DataObject``
        classes, ``fb.AUTO`` (AST-derive from the class's
        ``_make`` / ``_amake`` / ``_populate_*`` / ``_build_df`` /
        ``_make_data`` source), or ``None`` for a source asset.
    :param group: Dagster ``group_name``.
    :param convert_formats: Side formats to materialize after ``make``.
        Accepts ``StrEnum`` members (``fb.TableFormat.TSV``,
        ``fb.DocumentFormat.PDF``, ...) or their plain string values.
    :param convert: If ``True`` and ``convert_formats`` is empty,
        materialize **every** supported side format (legacy "all
        formats" shortcut).
    :param retries: Retry passes for request DBs.
    :param dagster_kwargs: Forwarded to ``@dg.asset(...)``. Use for
        ``tags``, ``owners``, ``metadata``, ``code_version``,
        ``automation_condition``, or any other Dagster ``@asset`` kwarg
        without waiting for a dedicated parameter. Keys that
        ``fb.asset(...)`` manages internally (``name``,
        ``partitions_def``, ``deps``, ``group_name``,
        ``required_resource_keys``) are rejected at build time.
    :returns: A class decorator that records the wiring on ``cls`` and
        registers it for discovery by ``fb.assets_from_module``.
    :raises TypeError: If applied to something that isn't a
        ``DagsterAssetWiring`` subclass (i.e. not a ``Table`` /
        ``Composite`` / ``Figure`` / ``Document`` / ``DB`` /
        ``HTTPDB`` / ``AgentDB`` / ``LLMDB`` descendant).
    :raises ValueError: If ``deps=fb.AUTO`` and the AST scan finds no
        upstream ``DataObject`` references (caller likely wants
        explicit ``deps=[...]`` or ``deps=None``).
    """

    def wrap(cls: T) -> T:
        if not issubclass(cls, DagsterAssetWiring):
            raise TypeError(
                f"@fb.asset requires a DataObject subclass that inherits "
                f"DagsterAssetWiring (Table/Composite/Figure/Document/DB/"
                f"HTTPDB/AgentDB/LLMDB or one of their subclasses). "
                f"Got {cls!r}."
            )

        if isinstance(deps, _Auto):
            resolved_deps: tuple[type[DataObject], ...] = (
                scan_make_for_data_object_refs(cls)  # type: ignore[arg-type]
            )
            if not resolved_deps:
                raise ValueError(
                    f"@fb.asset(deps=fb.AUTO) on {cls.__qualname__}: no "
                    f"upstream DataObject references found in scanned "
                    f"methods. Pass an explicit deps=[...] list or "
                    f"omit deps= for a source asset."
                )
        else:
            resolved_deps = tuple(deps or ())

        cls.asset_deps = resolved_deps  # type: ignore[attr-defined]
        cls.asset_group = group  # type: ignore[attr-defined]
        cls.asset_convert_formats = tuple(convert_formats or ())  # type: ignore[attr-defined]
        cls.asset_retries = retries  # type: ignore[attr-defined]
        cls.asset_convert = convert  # type: ignore[attr-defined]
        cls.asset_kwargs = dict(dagster_kwargs)  # type: ignore[attr-defined]

        DagsterAssetWiring._registry.append(cls)  # type: ignore[arg-type]
        return cls

    return wrap

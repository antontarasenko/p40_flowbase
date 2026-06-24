"""
Dagster integration for p40_flowbase.

Provides helpers for converting DataObject classes to Dagster assets:
- partitions_from_versions: Convert DataObjectVersion enums to StaticPartitionsDefinition
- get_version_from_partition: Look up version enum by partition key
- DataObjectIOManager: No-op IOManager for DataObject-backed assets
- ReplaceResource: Run-scoped switch to force re-creation of asset outputs
- asset: Factory for creating asset definitions from DataObject classes

Consumer projects MUST register ``ReplaceResource`` in their ``Definitions``
under the key ``"replace"``, e.g.::

    from p40_flowbase.dagster import ReplaceResource

    defs = dg.Definitions(
        assets=[...],
        resources={"replace": ReplaceResource()},
    )

Without it, asset materialization fails at run start with a missing-resource
error. To force re-creation of selected assets in a run, pass a run config
with ``replace=true``::

    dg launch --assets 'KEY+' --config-json \
        '{"resources":{"replace":{"config":{"replace":true}}}}'

or use a YAML file (e.g. ``replace.yaml``)::

    resources:
      replace:
        config:
          replace: true

    dg launch --assets 'KEY+' --config replace.yaml
"""

import contextlib
import graphlib
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum, StrEnum
from types import ModuleType
from typing import TYPE_CHECKING, Any, override

import dagster as dg

if TYPE_CHECKING:
    from p40_flowbase.core.base import DataObject

#: Override keys for ``assets_from_classes(overrides=...)`` / ``print_dag(...)``:
#: user-facing ``@fb.asset(...)`` parameter names that ``_wiring_for`` maps
#: to the underlying ``asset_*`` ``ClassVar`` storage names.
_OVERRIDE_KEYS: frozenset[str] = frozenset({
    "deps",
    "group",
    "convert_formats",
    "retries",
    "convert",
    "kwargs",
})

#: ``dg.asset(...)`` keyword arguments that ``_build_asset(...)`` already
#: manages internally. Forbidden inside the ``**dagster_kwargs`` escape
#: hatch and inside the ``asset_kwargs`` ``ClassVar``.
_RESERVED_DG_ASSET_KWARGS: frozenset[str] = frozenset({
    "name",
    "partitions_def",
    "deps",
    "group_name",
    "required_resource_keys",
})

#: Definition-time tag + metadata stamped onto any asset whose class sets
#: ``asset_rebuildable = False`` (e.g. ``ManualComposite``): flags in the UI
#: that data is managed out-of-band and rebuild paths are disabled.
_NOT_REBUILDABLE_TAGS: Mapping[str, str] = {"rebuildable": "false"}
_NOT_REBUILDABLE_METADATA: Mapping[str, Any] = {
    "rebuildable": False,
    "lifecycle": (
        "Not rebuildable: data is managed out-of-band (e.g. hand-uploaded "
        "files). replace, convert, and delete are disabled."
    ),
}


def partitions_from_versions(
    versions: tuple[Enum, ...],
) -> dg.StaticPartitionsDefinition:
    """Convert DataObjectVersion enum tuple to Dagster static partitions.

    :param versions: Tuple of version enum members with
        ``DataObjectVersion`` values.
    :returns: ``StaticPartitionsDefinition`` with partition keys
        derived from version IDs.
    """
    return dg.StaticPartitionsDefinition([
        v.value.id for v in versions
    ])


def get_version_from_partition(
    partition_key: str,
    version_enum_class: type[Enum],
) -> Enum:
    """Look up version enum member by partition key string.

    :param partition_key: The partition key string (matches
        ``DataObjectVersion.id``).
    :param version_enum_class: The Enum class containing version members.
    :returns: The matching enum member.
    :raises ValueError: If no version with the given ID exists.
    """
    for member in version_enum_class:
        if member.value.id == partition_key:
            return member
    raise ValueError(
        f"No version with id '{partition_key}' in {version_enum_class.__name__}"
    )


class DataObjectIOManager(dg.IOManager):
    """No-op IOManager for DataObject-backed assets.

    DataObjects handle their own file I/O internally via _make()
    and path_to_format(). This IOManager satisfies Dagster's requirement
    for a default IOManager without duplicating persistence logic.
    """

    def __init__(self, local_data: str) -> None:
        self.local_data = local_data

    @override
    def handle_output(self, context: dg.OutputContext, obj: object) -> None:
        pass

    @override
    def load_input(self, context: dg.InputContext) -> object:
        return None


class ReplaceResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Run-scoped switch to force re-creation of asset outputs.

    When ``replace`` is True, the asset factory bypasses the
    ``obj.exists()`` short-circuit and passes ``replace=True`` through to
    ``DataObject.make``/``DB.create_tables``/``DataObject.convert`` so the
    underlying on-disk data is wiped and rebuilt. When False (default),
    already-materialized assets are skipped — convenient for resuming a
    failed run by re-launching the same group.
    """

    replace: bool = False


class ConvertFormatsResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Run-scoped override of which side formats each asset materializes.

    When ``formats`` is non-empty, the asset factory ignores the
    static ``convert_formats`` parameter passed to ``fb.asset(...)`` and
    instead runs ``obj.convert(fmt)`` for every ``fmt.value`` in this
    list that the asset's format enum supports. Formats not supported by
    a given asset's enum are silently skipped, so a single global list
    (e.g. ``["csv", "svg"]``) flows across heterogeneous assets:
    ``csv`` hits Tables, ``svg`` hits Figures.

    Empty (default) means "use each asset's static ``convert_formats``
    parameter", or — when none was set and ``convert=False`` — produce
    no side formats at all.

    Override at launch time via ``--config-json``::

        --config-json '{
            "resources": {
                "convert_formats": {"config": {"formats": ["csv", "svg"]}}
            }
        }'

    From Python, the field accepts both plain strings and any
    ``StrEnum`` member (``fb.TableFormat.CSV``, ``fb.FigureFormat.SVG``,
    ...) — ``StrEnum`` is a subclass of ``str``, so the two forms are
    interchangeable at runtime::

        fb.ConvertFormatsResource(
            formats=[fb.TableFormat.CSV, fb.FigureFormat.SVG],
        )
    """

    formats: list[str] = []


def _build_asset(
    obj_class: type,
    partitions_def: dg.StaticPartitionsDefinition,
    version_enum_class: type[Enum],
    deps: list[Any] | None = None,
    retries: int = 0,
    convert: bool = False,
    convert_formats: Iterable[StrEnum | str] | None = None,
    group_name: str | None = None,
    **dagster_kwargs: Any,
) -> dg.AssetsDefinition:
    """Build a Dagster ``AssetsDefinition`` from a ``DataObject`` class.

    Internal helper called by ``assets_from_classes``. Users do not call
    this directly -- they wire assets via ``@fb.asset(...)`` and then
    feed the classes (or a module) to ``assets_from_classes`` /
    ``assets_from_module``.

    ``convert`` materializes **every** supported side format after
    ``make``; ``convert_formats`` is a static per-asset allowlist of
    plain strings and/or ``StrEnum`` members (normalized at
    registration; unsupported formats silently skipped). The two are
    mutually exclusive (``convert_formats`` wins), and the run-scoped
    ``ConvertFormatsResource.formats`` overrides both when non-empty.

    ``dagster_kwargs`` forwards extra ``@dg.asset(...)`` arguments (e.g.
    ``tags``, ``metadata``, ``code_version``); the factory's explicit
    kwargs win on key collisions.
    """
    conflicts = _RESERVED_DG_ASSET_KWARGS & dagster_kwargs.keys()
    if conflicts:
        raise ValueError(
            f"fb.asset(...) manages {sorted(conflicts)}; do not pass them via "
            f"**dagster_kwargs / asset_kwargs. Use the dedicated parameter "
            f"(e.g. group_name= for group_name)."
        )

    if not getattr(obj_class, "asset_rebuildable", True):
        # Mark out-of-band assets (e.g. ManualComposite) so the UI flags
        # them and a global rebuild skips them. User-supplied tags /
        # metadata win on key collisions.
        dagster_kwargs = {
            **dagster_kwargs,
            "tags": {**_NOT_REBUILDABLE_TAGS, **dagster_kwargs.get("tags", {})},
            "metadata": {
                **_NOT_REBUILDABLE_METADATA,
                **dagster_kwargs.get("metadata", {}),
            },
        }

    static_formats: list[str] | None = (
        [str(f) for f in convert_formats] if convert_formats is not None else None
    )
    is_db = hasattr(obj_class, "create_tables")
    is_graph_db = hasattr(obj_class, "_populate_lane_step")
    has_requests = (
        hasattr(obj_class, "_populate_http_requests")
        or hasattr(obj_class, "_populate_llm_requests")
        or hasattr(obj_class, "_populate_agent_tasks")
    )

    @dg.asset(
        **dagster_kwargs,
        name=obj_class.id,  # type: ignore[attr-defined]
        partitions_def=partitions_def,
        deps=deps or [],
        group_name=group_name,
        required_resource_keys={"replace", "convert_formats"},
    )
    async def _asset(context: dg.AssetExecutionContext) -> None:
        replace = context.resources.replace.replace
        runtime_formats: list[str] = [
            str(f) for f in context.resources.convert_formats.formats
        ]
        version = get_version_from_partition(
            context.partition_key,
            version_enum_class,
        )
        obj = obj_class(version)

        if is_db and is_graph_db:
            # Graph-based DB: lanes/steps are populated by execute_graph itself,
            # so calling populate() would duplicate the step-0 batch.
            await obj.make_graph(replace=replace)
            await obj.close()
        elif is_db and has_requests:
            # Request DBs are driven to completion on every run. With
            # `replace=False` (default) `make()` resumes pending/failed rows;
            # with `replace=True` the DB is wiped and a fresh group is run.
            await obj.make(replace=replace, retries=retries)
            await obj.close()
        elif obj.exists() and not replace:
            context.log.info(f"{obj.object_stem} already exists, skipping")
            return
        elif is_db:
            await obj.create_tables(replace=replace)
        else:
            # Use the async entry: sync `make()` calls `asyncio.run()`
            # internally for TableFromDB-style objects, which crashes inside
            # Dagster's running loop. `amake()` opens the per-object log
            # context and emits make_summary just like `make()`.
            await obj.amake(replace=replace)

        # Side-format resolution order:
        #   1. ConvertFormatsResource.formats (run-time override) wins.
        #   2. Else the asset's static convert_formats=[...] list.
        #   3. Else convert=True (legacy "all formats").
        # Unsupported formats are skipped, so one global list works
        # across heterogeneous assets.
        formats_to_run = runtime_formats or static_formats
        if formats_to_run:
            fmt_class: type[StrEnum] = type(obj.make_format)
            for fmt in fmt_class:
                if fmt == obj.make_format or fmt.value not in formats_to_run:
                    continue
                if replace:
                    obj.convert(fmt, replace=True)
                else:
                    with contextlib.suppress(FileExistsError):
                        obj.convert(fmt, replace=False)
        elif convert:
            if replace:
                obj.convert(replace=True)
            else:
                with contextlib.suppress(FileExistsError):
                    obj.convert(replace=False)

    # ``**dagster_kwargs: Any`` widens the @dg.asset overload set so pyright
    # cannot narrow the decorated return; the runtime type is correct.
    return _asset  # type: ignore[return-value]


def _label(cls: type) -> str:
    """Render a class label for error messages: ``QualName(id='...')``."""
    obj_id = getattr(cls, "id", None)
    base = cls.__qualname__
    return f"{base}(id={obj_id!r})" if obj_id is not None else base


def _wiring_for(
    cls: type["DataObject"],
    overrides: Mapping[type["DataObject"], Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Read effective asset wiring for ``cls``, applying per-call overrides.

    Falls back through: per-call override (short key) -> class
    ``asset_*`` ``ClassVar`` (storage name) -> default. Validates
    override keys against ``_OVERRIDE_KEYS``.
    """
    over = (overrides or {}).get(cls, {})
    bad = set(over.keys()) - _OVERRIDE_KEYS
    if bad:
        raise ValueError(
            f"Unknown override keys for {_label(cls)}: {sorted(bad)}. "
            f"Allowed: {sorted(_OVERRIDE_KEYS)}."
        )

    def pick(short_key: str, storage_attr: str, default: Any) -> Any:
        if short_key in over:
            return over[short_key]
        return getattr(cls, storage_attr, default)

    return {
        "deps": tuple(pick("deps", "asset_deps", ()) or ()),
        "group": pick("group", "asset_group", None),
        "convert_formats": tuple(
            pick("convert_formats", "asset_convert_formats", ()) or ()
        ),
        "retries": pick("retries", "asset_retries", 0),
        "convert": pick("convert", "asset_convert", False),
        "kwargs": dict(pick("kwargs", "asset_kwargs", {}) or {}),
    }


def assets_from_classes(
    classes: Sequence[type["DataObject"]],
    *,
    partitions_def: dg.StaticPartitionsDefinition,
    version_enum_class: type[Enum],
    overrides: Mapping[type["DataObject"], Mapping[str, Any]] | None = None,
) -> list[dg.AssetsDefinition]:
    """Build one ``dg.AssetsDefinition`` per class in dependency order.

    Reads asset wiring off each class's ``ClassVar``s
    (``asset_deps``, ``asset_group``, ``asset_convert_formats``,
    ``asset_retries``, ``asset_convert``, ``asset_kwargs``) instead of
    requiring a separate per-asset ``fb.asset(...)`` call site.
    Topologically sorts ``classes`` by ``asset_deps`` so each class's
    deps are already-built ``AssetsDefinition``\\ s by the time it is
    wrapped. Iteration over ``asset_deps`` preserves the user-declared
    tuple order, so ``dg.asset(deps=[...])`` arguments are deterministic
    across runs (no hash-randomization).

    The DAG is built only over the classes you pass in. A class listed in
    another class's ``asset_deps`` but missing from ``classes`` is an
    error: it would otherwise produce a Dagster asset graph with a
    dangling node and silently confuse selection. Duplicate classes in
    ``classes`` are likewise an error.

    :param classes: Subset of ``DataObject`` subclasses to register as
        Dagster assets.
    :param partitions_def: Partition definition shared by every asset.
    :param version_enum_class: Enum class for partition <-> version
        resolution; forwarded to ``asset(...)``.
    :param overrides: Per-class wiring overrides keyed by class. Each
        override mapping may set any of ``asset_deps``, ``asset_group``,
        ``asset_convert_formats``, ``asset_retries``, ``asset_convert``,
        ``asset_kwargs`` to override the corresponding ``ClassVar`` for
        this build only. Useful for parallel prod/staging/backfill
        ``Definitions`` over the same classes. Unknown keys raise.
    :returns: Built ``AssetsDefinition``\\ s, in topological order.
    :raises ValueError: If ``classes`` contains duplicates, if an
        ``asset_deps`` entry is not in ``classes``, if the deps form a
        cycle, or if ``overrides`` contains unknown keys.
    """
    seen: dict[type[DataObject], int] = {}
    duplicates: list[type[DataObject]] = []
    for cls in classes:
        seen[cls] = seen.get(cls, 0) + 1
        if seen[cls] == 2:
            duplicates.append(cls)
    if duplicates:
        raise ValueError(
            "Duplicate classes passed to assets_from_classes(): "
            f"{[_label(c) for c in duplicates]}."
        )

    class_set = set(classes)
    wiring: dict[type[DataObject], dict[str, Any]] = {
        cls: _wiring_for(cls, overrides) for cls in classes
    }
    graph: dict[type[DataObject], tuple[type[DataObject], ...]] = {}
    for cls in classes:
        deps = wiring[cls]["deps"]
        for dep in deps:
            if dep not in class_set:
                raise ValueError(
                    f"{_label(cls)}.asset_deps references "
                    f"{_label(dep)} ({dep.__module__}), which is not in "
                    f"the classes passed to assets_from_classes(). "
                    f"Add it to the classes list or remove the dep."
                )
        graph[cls] = deps

    sorter = graphlib.TopologicalSorter(graph)
    try:
        ordered = tuple(sorter.static_order())
    except graphlib.CycleError as exc:
        cycle = " -> ".join(_label(c) for c in exc.args[1])
        raise ValueError(f"asset_deps form a cycle: {cycle}") from exc

    built: dict[type[DataObject], dg.AssetsDefinition] = {}
    for cls in ordered:
        w = wiring[cls]
        built[cls] = _build_asset(
            cls,
            partitions_def=partitions_def,
            version_enum_class=version_enum_class,
            deps=[built[d] for d in graph[cls]] or None,
            retries=w["retries"],
            convert=w["convert"],
            convert_formats=w["convert_formats"] or None,
            group_name=w["group"],
            **w["kwargs"],
        )
    return [built[cls] for cls in ordered]


def print_dag(
    classes: Sequence[type["DataObject"]],
    *,
    overrides: Mapping[type["DataObject"], Mapping[str, Any]] | None = None,
) -> str:
    """Render an at-a-glance manifest of the asset DAG.

    Reads the same wiring ``ClassVar``s as ``assets_from_classes`` (and
    honors per-call ``overrides``), topo-sorts, then renders a fixed-
    width table:

    .. code-block:: text

        asset                 deps                   group  formats
        weather_input_cities  -                      -      -
        weather_http_db       weather_input_cities   -      -
        ...

    Restores the at-a-glance DAG view that lived in the old per-asset
    ``definitions.py``. Reviewers can drop ``print(fb.print_dag(ASSET_CLASSES))``
    next to the ``dg.Definitions(...)`` call to keep the manifest visible.

    :param classes: ``DataObject`` subclasses to render.
    :param overrides: Same shape as ``assets_from_classes(overrides=...)``.
        Useful for previewing the effective DAG of a staging variant.
    :returns: Multiline string ready to ``print``.
    """
    seen: set[type[DataObject]] = set()
    duplicates: list[type[DataObject]] = []
    for cls in classes:
        if cls in seen:
            duplicates.append(cls)
        seen.add(cls)
    if duplicates:
        raise ValueError(
            f"Duplicate classes passed to print_dag(): "
            f"{[_label(c) for c in duplicates]}."
        )

    wiring = {cls: _wiring_for(cls, overrides) for cls in classes}
    graph = {cls: wiring[cls]["deps"] for cls in classes}

    sorter = graphlib.TopologicalSorter(graph)
    try:
        ordered = tuple(sorter.static_order())
    except graphlib.CycleError as exc:
        cycle = " -> ".join(_label(c) for c in exc.args[1])
        raise ValueError(f"asset_deps form a cycle: {cycle}") from exc

    rows: list[tuple[str, str, str, str, str]] = [
        ("asset", "deps", "group", "formats", "kwargs"),
    ]
    for cls in ordered:
        w = wiring[cls]
        deps_str = ", ".join(
            getattr(d, "id", d.__qualname__) for d in graph[cls]
        ) or "-"
        group_str = w["group"] or "-"
        fmts_str = ", ".join(str(f) for f in w["convert_formats"]) or "-"
        kwargs_str = ", ".join(sorted(w["kwargs"])) or "-"
        rows.append((
            getattr(cls, "id", cls.__qualname__),
            deps_str,
            group_str,
            fmts_str,
            kwargs_str,
        ))

    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]
    return "\n".join(lines)


def assets_from_module(
    module: ModuleType,
    *,
    partitions_def: dg.StaticPartitionsDefinition,
    version_enum_class: type[Enum],
    overrides: Mapping[type["DataObject"], Mapping[str, Any]] | None = None,
) -> list[dg.AssetsDefinition]:
    """Build assets from every concrete ``DagsterAssetWiring`` subclass
    declared inside ``module`` (or any sub-module of it).

    Discovery walks ``DagsterAssetWiring._registry`` (populated by the
    mixin's ``__init_subclass__`` hook at class-body evaluation), filters
    to classes whose ``__module__`` lives within ``module`` 's package
    namespace, then forwards to :func:`assets_from_classes`.

    Use this when one Python package == one Dagster repo's worth of
    assets, and you don't want to hand-maintain the explicit
    ``ASSET_CLASSES`` tuple.

    :param module: The module (or package) whose ``DataObject``
        subclasses should be collected.
    :param partitions_def: Forwarded to ``assets_from_classes``.
    :param version_enum_class: Forwarded to ``assets_from_classes``.
    :param overrides: Forwarded to ``assets_from_classes``.
    :returns: Built ``AssetsDefinition``\\ s, in topological order.
    """
    from p40_flowbase.dagster.wiring import DagsterAssetWiring

    classes = DagsterAssetWiring.registered_for_module(module.__name__)
    return assets_from_classes(
        classes,
        partitions_def=partitions_def,
        version_enum_class=version_enum_class,
        overrides=overrides,
    )

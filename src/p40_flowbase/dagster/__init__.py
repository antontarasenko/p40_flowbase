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
from collections.abc import Iterable
from enum import Enum, StrEnum
from typing import Any

import dagster as dg


def partitions_from_versions(
    versions: tuple[Enum, ...],
) -> dg.StaticPartitionsDefinition:
    """Convert DataObjectVersion enum tuple to Dagster static partitions.

    :param versions: Tuple of version enum members with
        ``DataObjectVersion`` values.
    :type versions: tuple[Enum, ...]
    :returns: ``StaticPartitionsDefinition`` with partition keys
        derived from version IDs.
    :rtype: dg.StaticPartitionsDefinition
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
    :type partition_key: str
    :param version_enum_class: The Enum class containing version members.
    :type version_enum_class: type[Enum]
    :returns: The matching enum member.
    :rtype: Enum
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

    def handle_output(self, context: dg.OutputContext, obj: object) -> None:
        pass

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


def asset(
    obj_class: type,
    partitions_def: dg.StaticPartitionsDefinition,
    version_enum_class: type[Enum],
    deps: list[Any] | None = None,
    retries: int = 0,
    convert: bool = False,
    convert_formats: Iterable[StrEnum | str] | None = None,
    group_name: str | None = None,
) -> dg.AssetsDefinition:
    """Create a Dagster asset definition from a DataObject class.

    Generates an ``@asset`` function that materializes the DataObject by
    calling its ``make()`` or ``create_tables()`` method.

    :param obj_class: DataObject subclass to wrap.
    :type obj_class: type
    :param partitions_def: Partition definition for the asset.
    :type partitions_def: dg.StaticPartitionsDefinition
    :param version_enum_class: Enum class for resolving partition keys
        to versions.
    :type version_enum_class: type[Enum]
    :param deps: Upstream asset dependencies.
    :type deps: list[Any] | None
    :param retries: Number of retry passes for failed requests
        (DB mixin only).
    :type retries: int
    :param convert: Whether to materialize **every** supported side
        format after ``make``. Mutually exclusive with
        ``convert_formats``; the latter wins if both are set. The
        run-scoped ``ConvertFormatsResource`` (when its ``formats`` is
        non-empty) overrides both.
    :type convert: bool
    :param convert_formats: Static per-asset list of format values to
        materialize after ``make``. Accepts plain strings
        (``["csv", "json"]``) and/or ``StrEnum`` members
        (``[fb.TableFormat.CSV, fb.FigureFormat.SVG]``); members are
        normalized to their string values at registration time.
        Formats not supported by this asset's format enum are silently
        skipped. Overridden by ``ConvertFormatsResource.formats`` at
        run time when non-empty.
    :type convert_formats: Iterable[StrEnum | str] | None
    :param group_name: Dagster asset group name.
    :type group_name: str | None
    :returns: Dagster ``AssetsDefinition``.
    :rtype: dg.AssetsDefinition
    """
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
            # `obj.make()` is sync and would call `asyncio.run(_amake())`
            # internally for ``TableFromDB``-style objects, which crashes
            # inside Dagster's running loop. ``amake()`` is the async
            # lifecycle entry that opens the per-object log context and
            # emits ``make_summary`` exactly like ``make()`` does.
            await obj.amake(replace=replace)

        # Resolution order for which side formats to materialize:
        #   1. ConvertFormatsResource.formats (run-time override) wins.
        #   2. Else the asset's static convert_formats=[...] list.
        #   3. Else convert=True (legacy "all formats").
        # In the first two cases, format strings not supported by this
        # asset's enum are silently skipped, so a single global list
        # works across heterogeneous assets.
        formats_to_run = runtime_formats or static_formats
        if formats_to_run:
            fmt_class = type(obj.make_format)
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

    return _asset

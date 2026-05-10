"""Asset wiring trait.

``DagsterAssetWiring`` collects the ``ClassVar``s that
``p40_flowbase.dagster.assets_from_classes`` consumes when turning
``DataObject`` subclasses into Dagster assets. Concrete user-facing
``DataObject`` bases (``Table``, ``Composite``, ``Figure``, ``Document``,
``DB``) inherit this mixin so the Dagster-shaped fields don't pollute
pure-data classes (notably the SQLModel-style request/extra tables
generated via ``make_http_request_extra_table`` etc., which never
participate as Dagster assets).
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
)

if TYPE_CHECKING:
    from p40_flowbase.core.base import DataObject


class DagsterAssetWiring:
    """Asset-wiring ``ClassVar``s consumed by ``fb.assets_from_classes``.

    Storage type for the wiring set by ``@fb.asset(...)``. The decorator
    populates these attributes on the class and appends the class to
    ``_registry``; ``assets_from_classes`` / ``print_dag`` /
    ``lint_asset_deps`` / ``overrides=`` all read from here.

    The decorator is the only registration trigger. A subclass that
    sets these attributes by hand (or doesn't set them at all) is **not**
    a Dagster asset unless ``@fb.asset(...)`` is applied.

    :cvar asset_deps: Upstream classes this asset depends on.
        Members must themselves be passed to ``assets_from_classes``.
    :cvar asset_group: Optional Dagster group name.
    :cvar asset_convert_formats: Side formats to materialize after
        ``make`` (each entry may be a ``StrEnum`` member or its plain
        string value).
    :cvar asset_retries: Retry passes for request DBs.
    :cvar asset_convert: If True (and ``asset_convert_formats`` is
        empty), materialize **every** supported side format after
        ``make`` -- the legacy "all formats" shortcut.
    :cvar asset_kwargs: Generic escape hatch forwarded to
        ``@dg.asset(**asset_kwargs)``.
    """

    asset_deps: ClassVar[tuple[type["DataObject"], ...]] = ()
    asset_group: ClassVar[str | None] = None
    asset_convert_formats: ClassVar[tuple[StrEnum | str, ...]] = ()
    asset_retries: ClassVar[int] = 0
    asset_convert: ClassVar[bool] = False
    asset_kwargs: ClassVar[Mapping[str, Any]] = {}

    #: Classes registered by ``@fb.asset(...)``, in decoration order.
    #: Read by ``fb.assets_from_module(...)`` via
    #: :meth:`registered_for_module`; not part of the public API beyond
    #: that helper.
    _registry: ClassVar[list[type["DataObject"]]] = []

    @classmethod
    def registered_for_module(
        cls,
        module_name: str,
    ) -> list[type["DataObject"]]:
        """Return registered classes whose ``__module__`` is
        ``module_name`` or a sub-module of it."""
        prefix = module_name + "."
        return [
            c for c in cls._registry
            if c.__module__ == module_name or c.__module__.startswith(prefix)
        ]

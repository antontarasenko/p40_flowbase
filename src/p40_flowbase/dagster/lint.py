"""AST-based lint for ``asset_deps`` consistency.

Walks each class's data-producing methods (``_make``, ``_amake``,
``_populate_*``, ``_build_df``, ``_make_data``) for ``ast.Name``
references that resolve to ``DataObject`` subclasses in the class's
own module. Reports the diff against the class's declared
``asset_deps``.

Indirect references (via helper functions, dynamic class lookups,
string keys) are not detected; treat ``missing`` results as a hint,
not a hard contract.
"""

import ast
import inspect
import sys
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import override

from p40_flowbase.core.base import DataObject


#: Method names whose source we scan for upstream class references.
#: Covers all populate hooks, sync/async make, TableFromDB build, and
#: Document data-prep. Add new hooks here if the framework grows.
_SCANNED_METHODS: tuple[str, ...] = (
    "_make",
    "_amake",
    "_populate_http_requests",
    "_populate_llm_requests",
    "_populate_agent_tasks",
    "_populate_lane_step",
    "_build_df",
    "_make_data",
)


@dataclass(frozen=True)
class AssetDepsLintResult:
    """Diff between declared ``asset_deps`` and refs found in source.

    :ivar cls: The class that was scanned.
    :ivar declared: ``cls.asset_deps`` at scan time.
    :ivar referenced: Upstream ``DataObject`` classes found in scanned
        method bodies (excludes ``cls`` itself).
    :ivar missing: In ``referenced`` but not ``declared`` -- a likely
        gap in ``asset_deps``.
    :ivar unused: In ``declared`` but not ``referenced`` -- a stale
        entry, or an indirect reference the AST couldn't see.
    """

    cls: type[DataObject]
    declared: tuple[type[DataObject], ...]
    referenced: tuple[type[DataObject], ...]
    missing: tuple[type[DataObject], ...] = field(default=())
    unused: tuple[type[DataObject], ...] = field(default=())

    @property
    def is_clean(self) -> bool:
        """True iff ``missing`` and ``unused`` are both empty."""
        return not self.missing and not self.unused

    @override
    def __repr__(self) -> str:
        bits = [f"cls={self.cls.__qualname__}"]
        if self.missing:
            bits.append(f"missing={[c.__qualname__ for c in self.missing]}")
        if self.unused:
            bits.append(f"unused={[c.__qualname__ for c in self.unused]}")
        if self.is_clean:
            bits.append("clean=True")
        return f"AssetDepsLintResult({', '.join(bits)})"


def scan_make_for_data_object_refs(
    cls: type[DataObject],
) -> tuple[type[DataObject], ...]:
    """Return the set of ``DataObject`` subclasses referenced by ``cls``'s
    data-producing methods, in source-order, excluding ``cls`` itself.

    Resolves ``ast.Name`` and the head of ``ast.Attribute`` chains via
    ``sys.modules[cls.__module__]``. Symbols that don't resolve to a
    ``DataObject`` subclass are silently ignored, so unrelated names
    (locals, stdlib refs, sibling helpers) don't pollute the result.
    """
    module = sys.modules.get(cls.__module__)
    if module is None:
        return ()

    found: list[type[DataObject]] = []
    seen: set[type[DataObject]] = set()

    for method_name in _SCANNED_METHODS:
        method = cls.__dict__.get(method_name)
        if method is None:
            continue
        try:
            source = textwrap.dedent(inspect.getsource(method))
        except (OSError, TypeError):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            name: str | None = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                # Walk to the head of ``foo.bar.baz`` chains; only the
                # head (``foo``) is a candidate for module-level lookup.
                head = node
                while isinstance(head.value, ast.Attribute):
                    head = head.value
                if isinstance(head.value, ast.Name):
                    name = head.value.id

            if name is None:
                continue
            obj = getattr(module, name, None)
            if (
                isinstance(obj, type)
                and obj is not cls
                and issubclass(obj, DataObject)
                and obj not in seen
            ):
                seen.add(obj)
                found.append(obj)

    return tuple(found)


def lint_asset_deps(cls: type[DataObject]) -> AssetDepsLintResult:
    """Lint one class's ``asset_deps`` against its scanned source.

    :param cls: ``DataObject`` subclass to check.
    :returns: Diff record. Use ``.is_clean`` for a boolean gate.
    """
    declared: tuple[type[DataObject], ...] = tuple(
        getattr(cls, "asset_deps", ()) or ()
    )
    referenced = scan_make_for_data_object_refs(cls)
    declared_set: set[type[DataObject]] = set(declared)
    referenced_set: set[type[DataObject]] = set(referenced)
    missing = tuple(c for c in referenced if c not in declared_set)
    unused = tuple(c for c in declared if c not in referenced_set)
    return AssetDepsLintResult(
        cls=cls,
        declared=declared,
        referenced=referenced,
        missing=missing,
        unused=unused,
    )


def lint_asset_deps_all(
    classes: Iterable[type[DataObject]],
) -> list[AssetDepsLintResult]:
    """Lint a batch of classes; one result per class."""
    return [lint_asset_deps(c) for c in classes]

"""SQL+Jinja templates for ``Table`` materialization.

This module powers the *recommended convention* for defining a
``p40_flowbase.core.table.Table`` subclass: write **one
``.sql.jinja`` file per table, named ``<table.id>.sql.jinja``**, place
it under ``<your_pkg>/resources/templates/tables/``, and let
``Table._make()`` render → execute → validate → write for you. Users
do not write a ``_make`` body for the common case.

Layout
------
::

    your_pkg/
    ├── resources/
    │   └── templates/
    │       └── tables/
    │           └── widgets.sql.jinja      # filename MUST equal table.id
    └── objects/
        └── widgets.py                      # WidgetsTable + WidgetRow

``pyproject.toml`` (ships the templates with the wheel):

.. code-block:: toml

    [tool.setuptools.package-data]
    your_pkg = ["py.typed", "resources/templates/tables/*.sql.jinja"]

Schema sync (hard guarantee)
----------------------------
Before any parquet write, the Arrow schema returned by DuckDB is
compared against an Arrow schema derived from the Pydantic
``row_schema``. Missing columns, extra columns, and type-class
mismatches raise ``ValueError`` listing every diff. Stale or malformed
data never reaches disk.

The comparison is type-class-aware: any signed-integer Arrow type
matches a Python ``int`` field; any floating Arrow type matches a
Python ``float`` field; other types must match exactly. This lets
authors write ``::INTEGER``/``::BIGINT`` casts in SQL without forcing
a specific width on the Pydantic model.

Public API
----------
- :func:`render_sql_template` — load + Jinja-render an ``.sql.jinja``.
- :func:`arrow_schema_from_pydantic` — derive ``pa.Schema`` from a model.
- :func:`validate_arrow_against_pydantic` — raise on schema drift.

The full render → execute → validate → write pipeline is exposed as
``Table.make_via_sql_template`` (a method on
``p40_flowbase.core.table.Table``) so this module stays free of any
``Table`` dependency.
"""

import datetime as _dt
import decimal as _dc
import importlib.resources
import types as _types
import typing as _typing
from typing import (
    Any,
    get_args,
    get_origin,
)

import jinja2
import pyarrow as pa
import pydantic as pyd

# Runtime sentinel for the ``typing.Union`` origin; ``int | None``
# resolves to ``types.UnionType`` while ``Optional[int]`` resolves to
# this sentinel. ``getattr`` keeps pyright from flagging the deprecated
# ``typing.Union`` alias; we only need the runtime value.
_TYPING_UNION_ORIGIN: Any = getattr(_typing, "Union")  # noqa: B009


_PRIMITIVE_MAP: dict[Any, pa.DataType] = {
    int: pa.int64(),
    float: pa.float64(),
    bool: pa.bool_(),
    str: pa.string(),
    bytes: pa.binary(),
    _dt.datetime: pa.timestamp("us"),
    _dt.date: pa.date32(),
    _dc.Decimal: pa.decimal128(38, 18),
}


def _annotation_to_arrow(annotation: Any) -> tuple[pa.DataType, bool]:
    """Map a Pydantic field annotation to ``(arrow_type, nullable)``.

    Optional/Union with ``None`` becomes nullable. Non-None unions
    (e.g. ``int | str``) raise ``TypeError`` — there is no single
    Arrow type for them.
    """
    origin = get_origin(annotation)
    if origin is _TYPING_UNION_ORIGIN or origin is _types.UnionType:
        args = get_args(annotation)
        non_none = tuple(a for a in args if a is not type(None))
        nullable = len(non_none) < len(args)
        if len(non_none) != 1:
            raise TypeError(
                f"Cannot map Union {annotation!r} to a single Arrow type"
            )
        arrow_t, _ = _annotation_to_arrow(non_none[0])
        return arrow_t, nullable
    if annotation in _PRIMITIVE_MAP:
        return _PRIMITIVE_MAP[annotation], False
    raise TypeError(f"No Arrow mapping for Pydantic annotation {annotation!r}")


def arrow_schema_from_pydantic(model: type[pyd.BaseModel]) -> pa.Schema:
    """Derive a ``pa.Schema`` from a Pydantic ``BaseModel``.

    Supported scalars: ``int`` → ``int64``, ``float`` → ``float64``,
    ``bool`` → ``bool``, ``str`` → ``string``, ``bytes`` → ``binary``,
    ``datetime`` → ``timestamp[us]``, ``date`` → ``date32``,
    ``Decimal`` → ``decimal128(38, 18)``. ``Optional[T]`` becomes a
    nullable Arrow field. Unsupported types raise ``TypeError``.
    """
    fields: list[pa.Field[Any]] = []
    for name, info in model.model_fields.items():
        arrow_type, nullable = _annotation_to_arrow(info.annotation)
        fields.append(pa.field(name=name, type=arrow_type, nullable=nullable))
    return pa.schema(fields)


def _types_compatible(
    *,
    expected: pa.DataType,
    actual: pa.DataType,
) -> bool:
    """Type-class-aware equality.

    Exact match always passes. Any two signed integer types match;
    any two floating types match. This accommodates ``::INTEGER`` vs
    ``::BIGINT`` casts in SQL without forcing a specific width on the
    Pydantic side.
    """
    if expected.equals(actual):
        return True
    if pa.types.is_integer(expected) and pa.types.is_integer(actual):
        return True
    if pa.types.is_floating(expected) and pa.types.is_floating(actual):
        return True
    return False


def validate_arrow_against_pydantic(
    *,
    arrow_table: pa.Table,
    model: type[pyd.BaseModel],
) -> None:
    """Raise ``ValueError`` listing every column/type diff.

    Single raise with the full diff (does not short-circuit on the
    first error) so authors can fix all mismatches in one pass.
    """
    expected = arrow_schema_from_pydantic(model)
    actual = arrow_table.schema
    expected_names = set(expected.names)
    actual_names = set(actual.names)
    diffs: list[str] = []
    for name in expected.names:
        if name not in actual_names:
            diffs.append(f"missing column {name!r}")
            continue
        e_field = expected.field(name)
        a_field = actual.field(name)
        if not _types_compatible(expected=e_field.type, actual=a_field.type):
            diffs.append(
                f"column {name!r}: expected {e_field.type}, got {a_field.type}"
            )
    extra = sorted(actual_names - expected_names)
    if extra:
        diffs.append(f"unexpected columns: {extra}")
    if diffs:
        raise ValueError(
            f"Arrow table does not match Pydantic schema {model.__name__}: "
            + "; ".join(diffs)
        )


def render_sql_template(
    template_name: str,
    *,
    package: str,
    subpath: str = "resources/templates/tables",
    **template_vars: Any,
) -> str:
    """Render ``<package>/<subpath>/<template_name>`` with Jinja2.

    Args:
        template_name: Template file name, e.g. ``"widgets.sql.jinja"``.
        package: Anchor Python package; the loader walks
            ``importlib.resources.files(package).joinpath(subpath, template_name)``.
            ``subpath`` does **not** require ``__init__.py`` files —
            only ``package`` itself must be a real Python package.
        subpath: Directory inside ``package`` holding the templates.
            Defaults to the project convention.
        **template_vars: Variables passed into the Jinja render call.
    """
    root = importlib.resources.files(package)
    template_content = root.joinpath(subpath, template_name).read_text()
    env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=False)  # noqa: S701
    template = env.from_string(template_content)
    return template.render(**template_vars)

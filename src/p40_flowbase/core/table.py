"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
from abc import abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Generic,
    TypeVar,
    override,
)

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pydantic as pyd

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.database import DB
from p40_flowbase.core.formats import TableFormat
from p40_flowbase.helpers.sql_templates import (
    render_sql_template,
    validate_arrow_against_pydantic,
)


class Table(DataObject):
    """Tabular data object backed by a Parquet master file.

    Convention (zero-boilerplate ``_make``)
    ---------------------------------------
    Define a new ``Table`` with three pieces and **no** ``_make`` body:

    1. A Pydantic ``row_schema`` describing one row.
    2. A ``Table`` subclass with ``id``, ``description``,
       ``supported_versions``, and ``row_schema``.
    3. A SQL+Jinja template at
       ``<your_pkg>/resources/templates/tables/<id>.sql.jinja``.

    Calling ``MyTable(version).make()`` then:

    1. Renders ``<id>.sql.jinja`` with Jinja2.
    2. Executes the rendered SQL on a fresh in-memory DuckDB.
    3. Validates the resulting Arrow schema against ``row_schema``
       (hard ``ValueError`` on mismatch — stale data never reaches disk).
    4. Writes the validated Arrow table as Parquet (the master format).

    Example
    -------
    ``their_pkg/objects/widgets.py``::

        class WidgetRow(pyd.BaseModel):
            widget_id: int
            name: str

        class WidgetsTable(Table):
            id = "widgets"
            description = "Widget master table"
            supported_versions = (V.V1,)
            row_schema = WidgetRow

    ``their_pkg/resources/templates/tables/widgets.sql.jinja``::

        SELECT widget_id::BIGINT AS widget_id, name
        FROM read_parquet('{{ source }}')
        WHERE widget_id > 0;

    ``pyproject.toml`` (so the template ships with the wheel)::

        [tool.setuptools.package-data]
        their_pkg = ["py.typed", "resources/templates/tables/*.sql.jinja"]

    Escape hatches
    --------------
    Override ``_make`` if you need Jinja vars, want to register UDFs,
    or build the Arrow table without DuckDB. Always end your custom
    build by calling ``self.save_arrow(arrow)`` so schema validation
    still runs before write::

        @override
        def _make(self) -> None:
            self.make_via_sql_template(
                template_vars={"source": str(self.upstream_path)},
                duckdb_setup=lambda c: c.execute("SET TimeZone='UTC'"),
            )

    For non-template builds, do the work yourself and call
    ``self.save_arrow(arrow)`` to persist with validation.

    Attributes
    ----------
    row_schema:
        Pydantic model class defining one row of the output. Used both
        as documentation and as the source of truth for the pre-write
        Arrow schema check.
    template_package:
        Anchor Python package for the SQL template lookup. Defaults to
        the top-level package of the subclass module (e.g. ``their_pkg``
        for ``their_pkg.objects.widgets.WidgetsTable``). Override for
        nested-package layouts where the templates live in a different
        package than the class.

    Supported on-disk formats
    -------------------------
    PARQUET (master, default), CSV, TSV, JSON.
    """

    make_format: ClassVar[TableFormat] = TableFormat.PARQUET  # pyright: ignore[reportIncompatibleVariableOverride]
    row_schema: ClassVar[type[pyd.BaseModel]]
    template_package: ClassVar[str | None] = None

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self._table: pa.Table | None = None

    @property
    def df(self) -> pa.Table:
        """Return the object as a pyarrow Table (lazy loading)."""
        if self._table is None:
            self._table = pq.read_table(self.path_to_format(TableFormat.PARQUET))
        return self._table

    def save_arrow(self, arrow: pa.Table, *, validate: bool = True) -> None:
        """Validate ``arrow`` against ``row_schema`` then write parquet.

        This is the single write hook for every ``_make``/``_amake``
        body — the default ``_make`` calls it, ``make_via_sql_template``
        calls it, ``TableFromDB._amake`` calls it, and custom overrides
        should call it instead of ``pq.write_table`` directly so the
        schema check is never skipped by accident.

        Args:
            arrow: PyArrow table to persist.
            validate: When True (default), raise ``ValueError`` if the
                Arrow schema does not match ``row_schema``. Set to
                False only for performance-sensitive paths where you
                have already validated upstream.
        """
        if validate:
            validate_arrow_against_pydantic(
                arrow_table=arrow, model=self.row_schema,
            )
        pq.write_table(arrow, self.path_to_format(TableFormat.PARQUET))
        self._table = arrow

    def make_via_sql_template(
        self,
        *,
        template_name: str | None = None,
        package: str | None = None,
        subpath: str = "resources/templates/tables",
        template_vars: dict[str, Any] | None = None,
        duckdb_setup: Callable[[duckdb.DuckDBPyConnection], None] | None = None,
    ) -> None:
        """Render → execute → validate → write the master parquet file.

        Convention defaults:
            - ``template_name`` defaults to ``f"{self.id}.sql.jinja"``.
            - ``package`` defaults to ``self.template_package`` if set,
              otherwise the top-level Python package of the ``Table``
              subclass (``type(self).__module__.split(".")[0]``).

        Args:
            template_name: Override the convention-derived template name.
            package: Override the convention-derived anchor package.
            subpath: Override the convention-derived template subpath.
            template_vars: Variables passed into the Jinja render.
            duckdb_setup: Optional callback to register UDFs, attach
                databases, or configure the connection before the
                template SQL executes.
        """
        cls = type(self)
        resolved_pkg = (
            package or cls.template_package or cls.__module__.split(".")[0]
        )
        resolved_name = template_name or f"{self.id}.sql.jinja"
        sql = render_sql_template(
            template_name=resolved_name,
            package=resolved_pkg,
            subpath=subpath,
            **(template_vars or {}),
        )
        con = duckdb.connect(":memory:")
        try:
            if duckdb_setup is not None:
                duckdb_setup(con)
            arrow = con.execute(sql).to_arrow_table()
        finally:
            con.close()
        self.save_arrow(arrow)

    @override
    def _make(self) -> None:
        """Render ``<id>.sql.jinja`` via DuckDB, validate, write parquet.

        Default implementation following the project convention.
        Override in a subclass when you need Jinja vars, DuckDB setup,
        or a non-template build path; in that case call
        ``self.make_via_sql_template(...)`` (with custom kwargs) or
        ``self.save_arrow(arrow)`` (after building ``arrow`` yourself).
        """
        self.make_via_sql_template()

    @override
    def _make_summary(self) -> dict[str, Any]:
        df = self.df
        return {"rows": df.num_rows, "cols": df.num_columns}

    def _convert_to_csv(self) -> None:
        """Convert parquet to csv."""
        src = self.path_to_format(TableFormat.PARQUET)
        dst = self.path_to_format(TableFormat.CSV)
        duckdb.read_parquet(str(src)).write_csv(str(dst), header=True)

    def _convert_to_tsv(self) -> None:
        """Convert parquet to tsv."""
        src = self.path_to_format(TableFormat.PARQUET)
        dst = self.path_to_format(TableFormat.TSV)
        duckdb.read_parquet(str(src)).write_csv(str(dst), header=True, sep="\t")

    def _convert_to_json(self) -> None:
        """Convert parquet to json (array of records, indented)."""
        src = self.path_to_format(TableFormat.PARQUET)
        dst = self.path_to_format(TableFormat.JSON)
        rows = pq.read_table(src).to_pylist()
        dst.write_text(json.dumps(rows, indent=2, default=str))


TDB = TypeVar("TDB", bound=DB)


class TableFromDB(Table, Generic[TDB]):
    """Table built by extracting a pyarrow Table from a companion ``DB``.

    Subclasses set ``db_class`` and implement ``async _build_df(self, db)``.
    ``_amake`` opens the DB, builds the arrow table, calls
    ``self.save_arrow(...)`` (which validates against ``row_schema``
    before writing parquet), then closes the DB. No ``exists()``
    fallback — the upstream DB is assumed to already be materialized
    (in Dagster, ensure this via ``deps=[...]``).

    Example:
        class MyTable(TableFromDB[MyDB]):
            id = "my_table"
            db_class = MyDB
            row_schema = MyRowSchema
            supported_versions = (MyVersions.V1,)

            async def _build_df(self, db: MyDB) -> pa.Table:
                async with db.session_factory() as session:
                    rows = (await session.exec(select(MyRow))).all()
                return pa.Table.from_pylist([r.model_dump() for r in rows])
    """

    db_class: ClassVar[type[DB]]

    @abstractmethod
    async def _build_df(self, db: TDB) -> pa.Table:
        """Return a pyarrow Table extracted from ``db``.

        Subclasses must implement this method.
        """

    @override
    async def _amake(self) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        db: TDB = self.db_class(self.version)  # type: ignore[assignment]
        try:
            table = await self._build_df(db)
            self.save_arrow(table)
        finally:
            await db.close()

    @override
    def _make(self) -> None:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._amake())
        else:
            raise RuntimeError(
                "Cannot call make() from an async context. "
                "Use `await obj._amake()` instead."
            )

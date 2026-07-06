"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
import pathlib
from abc import abstractmethod
from collections.abc import Callable
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
from p40_flowbase.dagster.wiring import DagsterAssetWiring
from p40_flowbase.helpers.arrow_schema import (
    validate_arrow_against_pydantic,
    validate_arrow_schema_against_pydantic,
)
from p40_flowbase.helpers.jinja_templates import render_jinja_template


class Table(DataObject, DagsterAssetWiring):
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
    or build without a template::

        @override
        def _make(self) -> None:
            self.make_via_sql_template(
                template_vars={"source": str(self.upstream_path)},
                duckdb_setup=lambda c: c.execute("SET TimeZone='UTC'"),
            )

    Two write hooks, both schema-validate before persisting:

    - :meth:`save_sql` — stream a DuckDB query straight to parquet
      (``COPY (query) TO``). Never materializes the result in Python;
      use it for large or out-of-core builds.
    - :meth:`save_arrow` — persist a ``pa.Table`` you already hold in
      memory. Use it for small results or DB extractions (``TableFromDB``).

    Reading a Table into Python
    ---------------------------
    The single read surface is :meth:`sql`: it runs SQL over this
    object's master parquet, out-of-core, with the parquet exposed as
    the view ``t``. It returns a lazy DuckDB relation; only what you pull
    into Python lives in RAM::

        n = obj.sql("SELECT COUNT(*) FROM t").fetchone()[0]     # scalar, no materialize
        table = obj.sql().to_arrow_table()                               # whole table → pyarrow
        rows = obj.sql("SELECT city FROM t").to_arrow_table().to_pylist()

    Cross into Python through ``.to_arrow_table()`` (pyarrow is already a
    dependency); from a ``pa.Table`` use ``.to_pylist()``, column access,
    metadata. ``.to_arrow_table()`` materializes the **whole** table — bind it to a
    local and reuse that local as your cache, but **only for small
    tables**. The point of ``sql`` is to keep large tables out of RAM:
    filter/aggregate in SQL, or stream batches via
    ``obj.sql().to_arrow_reader(batch_size)``. Do not reach for ``.df()``
    / ``.pl()`` unless your project already depends on pandas / polars.

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
    PARQUET (master, default), CSV, TSV, JSON (newline-delimited). All
    side formats are produced by streaming the master parquet through
    DuckDB ``COPY``, so ``convert`` is bounded in memory.
    """

    make_format: ClassVar[TableFormat] = TableFormat.PARQUET  # pyright: ignore[reportIncompatibleVariableOverride]
    row_schema: ClassVar[type[pyd.BaseModel]]
    template_package: ClassVar[str | None] = None
    readme_kind: ClassVar[str] = "table"

    #: DuckDB ``memory_limit`` for :meth:`sql` / :meth:`save_sql` / convert.
    #: ``None`` keeps the DuckDB default (~80% of system RAM).
    sql_memory_limit: ClassVar[str | None] = None
    #: DuckDB ``temp_directory`` (spill target) for the same paths.
    #: ``None`` spills into the object's ``local_dir``.
    sql_temp_directory: ClassVar[str | None] = None

    def _duckdb_connection(self) -> duckdb.DuckDBPyConnection:
        """Return a DuckDB connection configured to spill to disk.

        Sets ``temp_directory`` (default: ``local_dir``) so large scans
        and aggregations spill instead of pressuring RAM, and
        ``memory_limit`` when ``sql_memory_limit`` is set. Shared by the
        query surface (:meth:`sql`), the streaming write (:meth:`save_sql`),
        and the format converters.
        """
        self.local_dir.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(":memory:")
        con.execute(
            "SET temp_directory = ?",
            [self.sql_temp_directory or str(self.local_dir)],
        )
        if self.sql_memory_limit is not None:
            con.execute("SET memory_limit = ?", [self.sql_memory_limit])
        return con

    def sql(self, query: str = "SELECT * FROM t") -> duckdb.DuckDBPyRelation:
        """Query this object's master parquet out-of-core; the table is ``t``.

        Returns a lazy DuckDB relation over the master parquet (exposed as
        the view ``t``). DuckDB streams and spills to ``temp_directory``;
        only the terminal you pull (``.to_arrow_table()``, ``.fetchone()``,
        ``.to_arrow_reader(n)``) lives in Python memory. See the class
        docstring for the full read path.
        """
        con = self._duckdb_connection()
        path = str(self.path_to_format(TableFormat.PARQUET)).replace("'", "''")
        con.execute(
            f"CREATE OR REPLACE VIEW t AS SELECT * FROM read_parquet('{path}')"  # noqa: S608
        )
        return con.sql(query)

    @property
    def path_to_schema(self) -> pathlib.Path:
        return self.local_dir / f"{self.object_stem}.schema.json"

    def row_schema_json(self) -> str:
        """Render ``row_schema`` as a standalone JSON Schema document.

        Deterministic, a pure function of the definition: pydantic's
        ``model_json_schema()`` (draft 2020-12) with the dialect ``$schema``
        key prepended. Keys are not sorted so field order is preserved.
        """
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **self.row_schema.model_json_schema(),
        }
        return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"

    def _write_schema(self) -> None:
        self.path_to_schema.write_text(self.row_schema_json())

    @override
    def _write_assets(self) -> None:
        super()._write_assets()
        self._write_schema()

    def save_arrow(self, arrow: pa.Table, *, validate: bool = True) -> None:
        """Validate an in-memory ``pa.Table`` against ``row_schema``, write parquet.

        The in-memory write hook: for results you already hold whole in
        RAM (small tables, ``pa.Table.from_pylist(...)`` builds, and
        ``TableFromDB._amake`` DB extractions). For large or out-of-core
        builds use :meth:`save_sql`, which never materializes the result.

        :param arrow: PyArrow table to persist.
        :param validate: When ``True`` (default), raise ``ValueError``
            if the Arrow schema does not match ``row_schema``. Set to
            ``False`` only for performance-sensitive paths where you
            have already validated upstream.
        """
        if validate:
            validate_arrow_against_pydantic(
                arrow_table=arrow, model=self.row_schema,
            )
        pq.write_table(arrow, self.path_to_format(TableFormat.PARQUET))

    def save_sql(
        self,
        query: str,
        *,
        duckdb_setup: Callable[[duckdb.DuckDBPyConnection], None] | None = None,
        validate: bool = True,
    ) -> None:
        """Stream a DuckDB ``query`` straight to the master parquet.

        The out-of-core write hook: ``COPY (query) TO parquet`` runs the
        query and writes the result to disk without ever materializing it
        in Python, so a build that scans/joins/aggregates hundreds of
        millions of rows stays bounded in memory. The query's output
        schema is derived from a zero-row relation and validated against
        ``row_schema`` **before** the write, so an invalid schema never
        reaches disk.

        :param query: A single ``SELECT`` statement (a trailing ``;`` is
            stripped). Reference upstream sources with ``read_parquet(...)``.
        :param duckdb_setup: Optional callback to register UDFs, attach
            databases, or configure the connection before execution.
        :param validate: When ``True`` (default), validate the output
            schema against ``row_schema`` before writing.
        """
        dst = str(self.path_to_format(TableFormat.PARQUET)).replace("'", "''")
        stmt = query.strip().rstrip(";").strip()
        con = self._duckdb_connection()
        try:
            if duckdb_setup is not None:
                duckdb_setup(con)
            if validate:
                schema = con.sql(stmt).limit(0).to_arrow_table().schema
                validate_arrow_schema_against_pydantic(
                    schema=schema, model=self.row_schema,
                )
            con.execute(f"COPY ({stmt}) TO '{dst}' (FORMAT parquet)")
        finally:
            con.close()

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

        :param template_name: Override the convention-derived template name.
        :param package: Override the convention-derived anchor package.
        :param subpath: Override the convention-derived template subpath.
        :param template_vars: Variables passed into the Jinja render.
        :param duckdb_setup: Optional callback to register UDFs, attach
            databases, or configure the connection before the template
            SQL executes.
        """
        from p40_flowbase.core.base import resolve_anchor_package

        resolved_pkg = package or resolve_anchor_package(self)
        resolved_name = template_name or f"{self.id}.sql.jinja"
        sql = render_jinja_template(
            template_name=resolved_name,
            package=resolved_pkg,
            subpath=subpath,
            **(template_vars or {}),
        )
        self.save_sql(sql, duckdb_setup=duckdb_setup)

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
        md = pq.read_metadata(self.path_to_format(TableFormat.PARQUET))
        return {"rows": md.num_rows, "cols": md.num_columns}

    @override
    def _readme_context(self) -> dict[str, Any]:
        """Add the data dictionary, one entry per ``row_schema`` field."""
        ctx = super()._readme_context()
        fields: list[dict[str, str]] = []
        for name, info in self.row_schema.model_fields.items():
            extra = info.json_schema_extra
            units = extra.get("units") if isinstance(extra, dict) else None
            fields.append(
                {
                    "id": name,
                    "name": info.title or "",
                    "description": info.description or "",
                    "units": str(units) if units is not None else "",
                }
            )
        ctx["fields"] = fields
        ctx["has_units"] = any(f["units"] for f in fields)
        return ctx

    @override
    def _meta_optional(self) -> dict[str, Any]:
        """Add Table-specific meta: row/col counts plus the schema pointer."""
        opt = super()._meta_optional()
        opt["schema"] = f"{self.object_stem}.schema.json"
        return opt

    def _copy_master_to(self, dst_fmt: TableFormat, copy_options: str) -> None:
        """Stream the master parquet to ``dst_fmt`` via DuckDB ``COPY``.

        Reads the master with ``read_parquet`` and writes the side format
        row-by-row, so a convert never holds the full table in memory.
        """
        src = str(self.path_to_format(TableFormat.PARQUET)).replace("'", "''")
        dst = str(self.path_to_format(dst_fmt)).replace("'", "''")
        con = self._duckdb_connection()
        try:
            con.execute(
                f"COPY (SELECT * FROM read_parquet('{src}')) "  # noqa: S608
                f"TO '{dst}' ({copy_options})"
            )
        finally:
            con.close()

    def _convert_to_csv(self) -> None:
        self._copy_master_to(TableFormat.CSV, "FORMAT csv, HEADER")

    def _convert_to_tsv(self) -> None:
        self._copy_master_to(TableFormat.TSV, "FORMAT csv, HEADER, DELIMITER '\t'")

    def _convert_to_json(self) -> None:
        """Convert parquet to newline-delimited JSON (one record per line)."""
        self._copy_master_to(TableFormat.JSON, "FORMAT json")


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

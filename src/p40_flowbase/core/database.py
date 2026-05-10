"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    override,
)

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import DBFormat
from p40_flowbase.dagster.wiring import DagsterAssetWiring

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        async_sessionmaker,
    )
    from sqlmodel.ext.asyncio.session import AsyncSession


class DB(DataObject, DagsterAssetWiring):
    """Base class for database data objects using async SQLAlchemy and SQLModel.

    Database objects store data in SQLite databases with async support.
    Supported formats:
        - SQLITE: SQLite database file (default)

    :cvar tables: List of SQLModel table classes to create.
    :vartype tables: list[Any]

    Subclasses should define their tables and can use HTTPDB/LLMDB/AgentDB
    mixins for request management.
    """

    make_format: ClassVar[DBFormat] = DBFormat.SQLITE  # pyright: ignore[reportIncompatibleVariableOverride]
    tables: ClassVar[list[Any]] = []

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @override
    def _make_summary(self) -> dict[str, Any]:
        return {"tables": len(self.tables)}

    def _get_database_url(self) -> str:
        """Return the async database URL."""
        return f"sqlite+aiosqlite:///{self.path_to_format(DBFormat.SQLITE)}"

    @property
    def engine(self) -> "AsyncEngine":
        """Return the async database engine (lazy loading)."""
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(
                self._get_database_url(),
                echo=False,
            )
        return self._engine

    @property
    def session_factory(self) -> "async_sessionmaker[AsyncSession]":
        """Return the async session factory."""
        if self._session_factory is None:
            from sqlalchemy.ext.asyncio import async_sessionmaker
            from sqlmodel.ext.asyncio.session import AsyncSession

            self._session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._session_factory

    async def get_session(self) -> "AsyncSession":
        """Get an async session context manager."""
        return self.session_factory()

    async def _create_tables(self) -> None:
        """Create tables defined in the ``tables`` attribute.

        If ``tables`` is non-empty, only those tables are created. Otherwise
        falls back to creating all tables registered with SQLModel.
        """
        from sqlmodel import SQLModel as SQLModelBase

        tables = [
            cls.__table__
            for cls in self.tables
            if hasattr(cls, "__table__")
        ]
        if tables:
            async with self.engine.begin() as conn:
                await conn.run_sync(
                    SQLModelBase.metadata.create_all,
                    tables=tables,
                )
        else:
            async with self.engine.begin() as conn:
                await conn.run_sync(SQLModelBase.metadata.create_all)

    async def _drop_tables(self) -> None:
        """Drop all tables defined in ``tables``."""
        from sqlmodel import SQLModel as SQLModelBase

        tables = [
            cls.__table__
            for cls in self.tables
            if hasattr(cls, "__table__")
        ]
        if tables:
            async with self.engine.begin() as conn:
                await conn.run_sync(
                    SQLModelBase.metadata.drop_all,
                    tables=tables,
                )
        else:
            async with self.engine.begin() as conn:
                await conn.run_sync(SQLModelBase.metadata.drop_all)

    @override
    def _make(self) -> None:
        """Create and save the default format (database file)."""
        self.local_dir.mkdir(parents=True, exist_ok=True)

        async def _async_make() -> None:
            await self._create_tables()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_async_make())
        else:
            raise RuntimeError(
                "Cannot call make() from async context. Use await create_tables() instead."
            )

    async def create_tables(self, replace: bool = False) -> None:
        """Create the database file and tables.

        Idempotent when ``replace=False``: ``_create_tables`` uses
        ``metadata.create_all``, which only creates missing tables. Existing
        tables and their rows are left untouched, so this can be called
        safely on a re-run of a Request-backed DB workflow.

        :param replace: If ``True``, delete existing master copy and
            all format copies, then create master copy anew.
        :type replace: bool
        """
        if replace:
            self.delete()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        await self._create_tables()

    async def convert_async(self, fmt: Any = None, replace: bool = False) -> None:
        """Async version of ``convert()`` for use in async contexts.

        :param fmt: Format to save. If ``None``, saves in all supported
            formats (excluding the default format).
        :type fmt: StrEnum | None
        :param replace: If ``True``, delete existing copy and recreate.
            If ``False``, raise when copy already exists.
        :type replace: bool
        :raises FileNotFoundError: If master copy doesn't exist.
        :raises FileExistsError: If a format copy exists and
            ``replace=False``.
        :raises ValueError: If ``fmt`` is not a supported format.
        """
        from enum import StrEnum

        if not self.exists():
            raise FileNotFoundError(
                f"Master copy not found for {self.object_stem}. "
                f"Call create_tables() first to create the master copy in {self.make_format.value} format."
            )

        if not isinstance(self.make_format, StrEnum):
            raise TypeError(
                f"{self.__class__.__name__} does not define make_format as a StrEnum"
            )

        format_class = type(self.make_format)

        if fmt is None:
            formats_to_create = [
                f for f in format_class if f != self.make_format  # type: ignore[redundant-expr]
            ]
        else:
            if not isinstance(fmt, StrEnum):
                raise ValueError(
                    f"Format must be a StrEnum type. "
                    f"Supported formats: {list(format_class)}"
                )
            if not isinstance(fmt, format_class):
                raise ValueError(
                    f"Format '{fmt}' not supported. Supported formats: {list(format_class)}"
                )
            if fmt == self.make_format:
                return
            formats_to_create = [fmt]  # type: ignore[unreachable]

        for fmt_enum in formats_to_create:
            format_path = self.path_to_format(fmt_enum)
            if format_path.exists() and not replace:
                raise FileExistsError(
                    f"Format '{fmt_enum.value}' already exists for {self.object_stem}. "
                    f"Use replace=True to overwrite."
                )
            if format_path.exists() and replace:
                self._delete_format(fmt_enum)

        self._convert_formats(formats_to_create)

    async def close(self) -> None:
        """Close the database engine and cleanup resources."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

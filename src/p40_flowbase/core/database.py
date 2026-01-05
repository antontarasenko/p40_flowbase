"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
from typing import (
    Any,
    List,
)

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import DBFormat
from p40_flowbase.logging import logger


class DBDataObject(DataObject):
    """Base class for database data objects using async SQLAlchemy and SQLModel.

    Database objects store data in SQLite databases with async support.
    Supported formats:
        - SQLITE: SQLite database file (default)

    Attributes:
        schema: List of SQLModel table classes to create.

    Subclasses should define their schema and can use HTTP/LLM mixins
    for request management.
    """

    make_format: DBFormat = DBFormat.SQLITE
    schema: List[Any] = []

    def __init__(self, version):
        super().__init__(version)
        self._engine = None
        self._session_factory = None

    def _get_database_url(self) -> str:
        """Return the async database URL."""
        return f"sqlite+aiosqlite:///{self.path_to_format(DBFormat.SQLITE)}"

    @property
    def engine(self):
        """Return the async database engine (lazy loading)."""
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(
                self._get_database_url(),
                echo=False,
            )
        return self._engine

    @property
    def session_factory(self):
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

    async def get_session(self):
        """Get an async session context manager."""
        return self.session_factory()

    async def _create_tables(self) -> None:
        """Create all tables defined in schema."""
        from sqlmodel import SQLModel as SQLModelBase

        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModelBase.metadata.create_all)

    async def _drop_tables(self) -> None:
        """Drop all tables defined in schema."""
        from sqlmodel import SQLModel as SQLModelBase

        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModelBase.metadata.drop_all)

    def _make_default(self) -> None:
        """Create and save the default format (database file)."""
        self.local_dir.mkdir(parents=True, exist_ok=True)

        async def _async_make():
            await self._create_tables()

        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "Cannot call make() from async context. Use await make_async() instead."
            )
        except RuntimeError as e:
            if "Cannot call make()" in str(e):
                raise
            asyncio.run(_async_make())

    async def make_async(self, replace: bool = False) -> None:
        """Async version of make() for use in async contexts.

        Args:
            replace: If True, delete existing master copy and all format copies,
                then create master copy anew. If False, raise error if master
                copy already exists.

        Raises:
            FileExistsError: If master copy exists and replace=False.
        """
        if self.path_to_format(self.make_format).exists() and not replace:
            raise FileExistsError(
                f"Object {self.object_stem} already exists in default format ({self.make_format.value}). "
                f"Use replace=True to overwrite."
            )

        if replace:
            self._delete_existing_formats()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        await self._create_tables()
        logger.info(f"{self.object_stem} created successfully")

    async def convert_async(self, fmt=None, replace: bool = False) -> None:
        """Async version of convert() for use in async contexts.

        Args:
            fmt: Format to save (StrEnum). If None, saves in all supported formats
                (excluding the default format).
            replace: If True, delete existing copy and recreate. If False, raise
                error if copy already exists.

        Raises:
            FileNotFoundError: If master copy doesn't exist.
            FileExistsError: If format copy exists and replace=False.
            ValueError: If fmt is not a supported format.
        """
        from enum import StrEnum

        if not self.path_to_format(self.make_format).exists():
            raise FileNotFoundError(
                f"Master copy not found for {self.object_stem}. "
                f"Call make_async() first to create the master copy in {self.make_format.value} format."
            )

        if not isinstance(self.make_format, StrEnum):
            raise ValueError(
                f"{self.__class__.__name__} does not define make_format as a StrEnum"
            )

        format_class = type(self.make_format)

        if fmt is None:
            formats_to_create = [f for f in format_class if f != self.make_format]
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
            formats_to_create = [fmt]

        for fmt_enum in formats_to_create:
            format_path = self.path_to_format(fmt_enum)
            if format_path.exists() and not replace:
                raise FileExistsError(
                    f"Format '{fmt_enum.value}' already exists for {self.object_stem}. "
                    f"Use replace=True to overwrite."
                )
            elif format_path.exists() and replace:
                self._delete_format(fmt_enum)

        self._convert_formats(formats_to_create)

    async def close(self) -> None:
        """Close the database engine and cleanup resources."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

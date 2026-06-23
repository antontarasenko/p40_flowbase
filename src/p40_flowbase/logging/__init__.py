"""Logging configuration for p40_flowbase.

Module exports:

- ``logger`` — the package-wide ``logging.Logger`` named ``p40_flowbase``.
- ``object_log_context`` — context manager that, while active, attaches
  a ``FileHandler`` for one ``DataObject``'s ``<object_stem>.meta.log`` to
  the package logger and binds ``_current_object_stem`` so a per-handler
  ``Filter`` accepts only that object's records.

Concurrency model
-----------------
The current-object identifier lives in a ``contextvars.ContextVar``.
``ContextVar`` values are coroutine-local (per asyncio task) and
thread-local (per ``threading.Thread`` if they enter the manager
themselves), so two ``DataObject.make()`` calls running concurrently
each see only their own bound stem and write only their own messages
to their per-object log file.
"""

import contextlib
import contextvars
import logging
import pathlib
from collections.abc import Iterator
from typing import override

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("p40_flowbase")


_current_object_stem: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "p40_flowbase_current_object_stem",
    default=None,
)


class _ObjectFilter(logging.Filter):
    """Accept records iff the bound ``object_stem`` is the current one."""

    def __init__(self, object_stem: str) -> None:
        super().__init__()
        self.object_stem = object_stem

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        del record
        return _current_object_stem.get() == self.object_stem


@contextlib.contextmanager
def object_log_context(
    *,
    object_stem: str,
    local_dir: pathlib.Path,
    phase: str,
) -> Iterator[None]:
    """Bind ``object_stem``, attach a per-object ``FileHandler``, log a marker.

    On enter: sets the contextvar, ensures ``local_dir`` exists,
    attaches a ``FileHandler`` (append mode, UTF-8) to the
    ``p40_flowbase`` logger with an ``_ObjectFilter``. On exit: writes
    the end marker, detaches and closes the handler, resets the
    contextvar.

    :param object_stem: Unique key identifying the data object
        (``f"{id}-{version.value.id}"``).
    :param local_dir: Directory where the ``<object_stem>.meta.log`` file
        lives. Created if missing.
    :param phase: One of ``"make"``, ``"convert"``, ``"delete"`` —
        used in the begin/end markers written to the log.
    """
    token = _current_object_stem.set(object_stem)
    local_dir.mkdir(parents=True, exist_ok=True)
    log_path = local_dir / f"{object_stem}.meta.log"
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    handler.addFilter(_ObjectFilter(object_stem))
    logger.addHandler(handler)
    logger.info(f"=== begin {phase} | object={object_stem} ===")
    try:
        yield
    finally:
        logger.info(f"=== end {phase} | object={object_stem} ===")
        logger.removeHandler(handler)
        handler.close()
        _current_object_stem.reset(token)


__all__ = [
    "logger",
    "object_log_context",
]

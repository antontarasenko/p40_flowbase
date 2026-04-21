"""Core data object classes and format enums."""

from p40_flowbase.core.base import (
    DataObject,
    DataObjectVersion,
)
from p40_flowbase.core.composite import Composite
from p40_flowbase.core.database import DB
from p40_flowbase.core.document import Document
from p40_flowbase.core.figure import Figure
from p40_flowbase.core.formats import (
    CompositeFormat,
    DBFormat,
    DocumentFormat,
    FigureFormat,
    ModelFormat,
    TableFormat,
)
from p40_flowbase.core.model import Model
from p40_flowbase.core.table import (
    Table,
    TableFromDB,
)
from p40_flowbase.core.tables import (
    make_agent_task_extra_table,
    make_agent_task_group_table,
    make_http_request_extra_table,
    make_http_request_group_table,
    make_llm_request_extra_table,
    make_llm_request_group_table,
)

__all__ = [
    # Base
    "DataObject",
    "DataObjectVersion",
    # Data object types
    "Composite",
    "DB",
    "Document",
    "Figure",
    "Model",
    "Table",
    "TableFromDB",
    # Formats
    "CompositeFormat",
    "DBFormat",
    "DocumentFormat",
    "FigureFormat",
    "ModelFormat",
    "TableFormat",
    # SQLModel table factories
    "make_agent_task_extra_table",
    "make_agent_task_group_table",
    "make_http_request_extra_table",
    "make_http_request_group_table",
    "make_llm_request_extra_table",
    "make_llm_request_group_table",
]

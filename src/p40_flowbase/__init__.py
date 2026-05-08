"""
p40_flowbase - Data pipeline framework for structured data workflows.

MIT License
Copyright (c) 2025 Anton Tarasenko
"""

from importlib.metadata import version

from p40_flowbase.agents import (
    AgentDB,
    AgentFile,
    AgentMessage,
    AgentTask,
    AgentTaskExtra,
    AgentTaskGroup,
    AgentToolCall,
)
from p40_flowbase.config import BaseFlowSettings
from p40_flowbase.core import (
    DB,
    Composite,
    CompositeFormat,
    DataObject,
    DataObjectVersion,
    DBFormat,
    Document,
    DocumentFormat,
    Figure,
    FigureFormat,
    Model,
    ModelFormat,
    Table,
    TableFormat,
    TableFromDB,
    make_agent_task_extra_table,
    make_agent_task_group_table,
    make_http_request_extra_table,
    make_http_request_group_table,
    make_llm_request_extra_table,
    make_llm_request_group_table,
)
from p40_flowbase.dagster import (
    DataObjectIOManager,
    ReplaceResource,
    asset,
    get_version_from_partition,
    partitions_from_versions,
)
from p40_flowbase.helpers import (
    extract_json_from_response,
    render_prompt_template,
    safe_path_component,
)
from p40_flowbase.http import (
    HTTPDB,
    HostCoordinator,
    HTTPRequest,
    HTTPRequestExtra,
    HTTPRequestGroup,
)
from p40_flowbase.llm import (
    LLMDB,
    LLMFile,
    LLMRequest,
    LLMRequestExtra,
    LLMRequestGroup,
)
from p40_flowbase.logging import logger
from p40_flowbase.providers import (
    AGENT_SUPPORTED_PROVIDERS,
    Models,
    ModelVersion,
    Providers,
)
from p40_flowbase.styles import (
    STYLES,
    apply_style,
)

__version__ = version("p40_flowbase")

__all__ = [
    "AGENT_SUPPORTED_PROVIDERS",
    "DB",
    "HTTPDB",
    "LLMDB",
    "STYLES",
    "AgentDB",
    "AgentFile",
    "AgentMessage",
    "AgentTask",
    "AgentTaskExtra",
    "AgentTaskGroup",
    "AgentToolCall",
    "BaseFlowSettings",
    "Composite",
    "CompositeFormat",
    "DBFormat",
    "DataObject",
    "DataObjectIOManager",
    "DataObjectVersion",
    "Document",
    "DocumentFormat",
    "Figure",
    "FigureFormat",
    "HTTPRequest",
    "HTTPRequestExtra",
    "HTTPRequestGroup",
    "HostCoordinator",
    "LLMFile",
    "LLMRequest",
    "LLMRequestExtra",
    "LLMRequestGroup",
    "Model",
    "ModelFormat",
    "ModelVersion",
    "Models",
    "Providers",
    "ReplaceResource",
    "Table",
    "TableFormat",
    "TableFromDB",
    "__version__",
    "apply_style",
    "asset",
    "extract_json_from_response",
    "get_version_from_partition",
    "logger",
    "make_agent_task_extra_table",
    "make_agent_task_group_table",
    "make_http_request_extra_table",
    "make_http_request_group_table",
    "make_llm_request_extra_table",
    "make_llm_request_group_table",
    "partitions_from_versions",
    "render_prompt_template",
    "safe_path_component",
]

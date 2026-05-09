"""p40_flowbase — single-dependency data processing framework.

Pipelines are built from ``DataObject`` subclasses: ``Table``,
``Composite``, ``DB`` (with ``HTTPDB`` / ``LLMDB`` / ``AgentDB``
mixins), ``Document``, ``Figure``, ``Model``. Every object exposes the
same three-method lifecycle (``make`` / ``convert`` / ``delete``) and
ships a per-object log file at ``<local_dir>/<object_stem>.meta.log``.
Dagster asset wrappers are first-class: ``fb.asset(MyTable, …)`` turns
any ``DataObject`` subclass into a partitioned, dependency-aware asset.

Sample project
--------------

A complete worked example lives at ``examples/p40_weather/`` in the
``p40_flowbase`` source repo — a standalone ``p40-weather`` project
that depends on this framework as its single dependency and builds the
canonical pipeline against the free Open-Meteo API::

    HTTPDB → Composite → Table → summary Table → Figure → Document

Read it as the reference layout for ``pyproject.toml``, the
``objects/`` / ``helpers/`` / ``resources/templates/{tables,documents}/``
folder layout, and a full Dagster ``Definitions`` graph.

Lifecycle
---------

Every data object exposes the same three methods::

    from p40_weather.objects import WeatherSummaryTable
    from p40_weather.versions import V
    from p40_flowbase import TableFormat

    DataObject.set_local_data("/tmp/p40_weather_data")

    t = WeatherSummaryTable(V.V1)
    t.make()                        # build the parquet master file
    t.convert(TableFormat.CSV)      # add a CSV side-format
    t.delete()                      # remove all on-disk artifacts

Run as a Dagster pipeline
-------------------------

::

    cd examples/p40_weather
    pip install -e .
    dg dev -m p40_weather.definitions          # web UI; materialize all assets
    # …or one-shot:
    dg launch -m p40_weather.definitions --select '*'

Force re-creation of selected assets via the ``replace`` resource::

    dg launch -m p40_weather.definitions --select 'weather_summary_table+' \\
        --config-json '{"resources":{"replace":{"config":{"replace":true}}}}'

Plug in additional LLM models (advanced)
----------------------------------------

The ``p40_flowbase.providers`` module ships a curated ``Models``
catalog (Claude, Gemini, GPT, …) plus three ways to add your own:

1. **Built-in:** ``Models.CLAUDE_OPUS_4_7`` is a ``ModelVersion`` —
   pass it directly to ``LLMRequest.from_spec(...)``.
2. **Ad hoc:** construct a ``ModelVersion`` inline (useful for dated
   snapshots, fine-tunes, OpenAI-compatible proxies)::

       from p40_flowbase import ModelVersion, Providers

       MY_PROXY = ModelVersion(
           id="my_proxy_gpt",
           api_id="custom-proxy-gpt-5-5",
           name="Internal proxy",
           provider=Providers.OPENAI,
           input_token_price_usd=0.000005,
           output_token_price_usd=0.000030,
       )
3. **Subclass ``Models``** to keep autocomplete on a project-local
   catalog while inheriting the built-ins. See the full pattern in
   ``help(p40_flowbase.providers)``.

License: MIT. Copyright (c) 2025 Anton Tarasenko.
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
    ConvertFormatsResource,
    DataObjectIOManager,
    ReplaceResource,
    asset,
    get_version_from_partition,
    partitions_from_versions,
)
from p40_flowbase.helpers import (
    extract_json_from_response,
    render_jinja_template,
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
    "ConvertFormatsResource",
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
    "render_jinja_template",
    "safe_path_component",
]

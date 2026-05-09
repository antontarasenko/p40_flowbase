# Changelog

## Branch `main`

- Rewrite docstrings in Sphinx reST (pep257) instead of Google style; add example project `p40_weather`
- Improve logging: per-object .log file, summary stats, progress reports
- Move `claude-agent-sdk`, `openai-agents`, `langgraph` to optional extras; users pin their own versions
- Allow users add their own models
- Add models `claude_opus_4_7`, `gpt_5_5`, `gpt_5_5_pro`, `gemini_3_1_pro_preview`, `gemini_3_1_flash_lite`
- Promote `gemini_3_flash` from preview to GA
- Replace deprecated `gemini_3_pro_preview` with `gemini_3_1_pro_preview`
- Add effort to Gemini `thinkingConfig`
- Bump versions in dependencies `claude-agent-sdk`, `langgraph`, `openai-agents`
- Replace `pandas` with `duckdb`, `pyarrow` in `Table`
- Drop support for Markdown format (`TableFormat.MD`) in `Table`
- devel: Tighten tooling config (`basedpyright`, `ruff`, `mypy`, `pytest`)
- devel: Fix issues raised by `basedpyright`, `ruff`, `mypy`

## 0.4.0 (2026-04-23)

- Migrate package to Dagster

## 0.3.1 (2026-04-18)

- Pin `claude-agent-sdk` version (0.1.* versioning is too broad)
- devel: Publish package on PyPI (starting from 0.3.0)
- Fix `get_existing_formats` missing folders in `CompositeFormat`
- Upgrade dependencies `claude-agent-sdk`, `openai-agents`, `langgraph`
- devel: Specify package version for Nix in `VERSION` file
- Add models `claude_opus_4_6`, `claude_sonnet_4_6`, `gpt_5_4`, `gpt_5_4_mini`
- Add `effort` parameter to models

## 0.3.0 (2026-04-11)

- Upgrade `claude-agent-sdk` from 0.1.39 to 0.1.48
- Fix `rate_limit_event` error
- Rename `data_local_tmp` to `local_data`

## 0.2.3 (2026-03-03)

- Fix parallel lane processing
- Fix error when `max_rate` in `aiolimiter` is less than 1
- devel: Set strict code quality checks
- devel: Sort imports, replace `Optional[*] = None` patterns
- devel: Add `.git-blame-ignore-revs`

## 0.2.2 (2026-02-21)

- Fix `process_step` in graph operations

## 0.2.1 (2026-02-21)

- Enable versioning with `setuptools-scm`

## 0.2.0 (2026-02-21)

- Update `claude-agent-sdk` and `openai-agents` to later versions
- Fix `retry` in requests when failed retries get duplicated
- tests: Add `tests` to test package directly, not via examples
- Add `DataObject.exists()` method to check master copy's availability
- Add `delete` command to object manager scripts
- Fix `additionalProperties: false` issue in structured LLM output
- Allow object-level defaults `rate_limit` and `rate_period` for requests
- Fix misc issues across package (see commit for details)
- Add support for recursive tasks and requests via LangGraph orchestration
- Move `agents` and `langgraph` dependencies to main dependencies
- Update `claude-agent-sdk` and `openai-agents` to their latest versions

## 0.1.4

- Fix LLM model versions used in agent tasks
- Fix logging of agent tool use in agent tasks

## 0.1.3

- Add structured output to agent tasks
- Fix manager commands for agent objects

## 0.1.2

- Add agent tasks (Claude Agent and OpenAI Agents)
- Switch `nixpkgs` from NixOS 25.05 to 25.11
- Get Python dependencies from PyPI, instead of `nixpkgs`, and pin them with `uv.lock`
- Update Python dependencies in `pyproject.toml` to the versions supplied for NixOS 25.11

## 0.1.1

- Fix LLM API authentication in subprojects
- Fix the missing `data_local_tmp`

## 0.1.0

Init

# Changelog

## Branch `main`

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

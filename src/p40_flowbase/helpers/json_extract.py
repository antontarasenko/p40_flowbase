"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
import re
from typing import Any


def extract_json_from_response(response_text: str | None) -> dict[str, Any] | None:
    """Extract a JSON object from model response text.

    Tries in order:
        1. Parse the whole response as JSON.
        2. Parse the contents of a ```json fenced code block.
        3. Match a brace-balanced substring and parse it.

    Returns None if no valid JSON object can be found.
    """
    if not response_text:
        return None

    parsed: dict[str, Any] | None = _try_parse(response_text)
    if parsed is not None:
        return parsed

    code_block_match = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```",
        response_text,
        re.DOTALL,
    )
    if code_block_match:
        parsed = _try_parse(code_block_match.group(1).strip())
        if parsed is not None:
            return parsed

    json_match = re.search(
        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
        response_text,
        re.DOTALL,
    )
    if json_match:
        parsed = _try_parse(json_match.group(0))
        if parsed is not None:
            return parsed

    return None


def _try_parse(text: str) -> dict[str, Any] | None:
    try:
        result: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None

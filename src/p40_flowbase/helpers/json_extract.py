"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import json
import re


def extract_json_from_response(response_text: str | None) -> dict | None:
    """Extract a JSON object from model response text.

    Tries in order:
        1. Parse the whole response as JSON.
        2. Parse the contents of a ```json fenced code block.
        3. Match a brace-balanced substring and parse it.

    Returns None if no valid JSON object can be found.
    """
    if not response_text:
        return None

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    code_block_match = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```",
        response_text,
        re.DOTALL,
    )
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    json_match = re.search(
        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
        response_text,
        re.DOTALL,
    )
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None

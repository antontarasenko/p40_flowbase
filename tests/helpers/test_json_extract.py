"""Tests for ``extract_json_from_response``."""

from p40_flowbase.helpers.json_extract import extract_json_from_response


class TestExtractJsonFromResponse:
    def test_none_returns_none(self):
        assert extract_json_from_response(None) is None

    def test_empty_string_returns_none(self):
        assert extract_json_from_response("") is None

    def test_raw_json_object(self):
        assert extract_json_from_response('{"foo": "bar"}') == {"foo": "bar"}

    def test_raw_nested_json(self):
        text = '{"outer": {"inner": 42}}'
        assert extract_json_from_response(text) == {"outer": {"inner": 42}}

    def test_json_fenced_code_block(self):
        text = '```json\n{"foo": "bar"}\n```'
        assert extract_json_from_response(text) == {"foo": "bar"}

    def test_unlabelled_fenced_code_block(self):
        text = '```\n{"foo": 1}\n```'
        assert extract_json_from_response(text) == {"foo": 1}

    def test_json_in_surrounding_prose(self):
        text = 'Here is the result:\n{"status": "ok"}\nThat is it.'
        assert extract_json_from_response(text) == {"status": "ok"}

    def test_malformed_json_returns_none(self):
        assert extract_json_from_response("{not: valid json") is None

    def test_prose_without_json_returns_none(self):
        assert extract_json_from_response("no json here") is None

    def test_prefers_raw_parse_over_code_block(self):
        text = '{"a": 1}'
        assert extract_json_from_response(text) == {"a": 1}

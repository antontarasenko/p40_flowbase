"""Tests for ``safe_path_component``."""

from p40_flowbase.helpers.paths import safe_path_component


class TestSafePathComponent:
    def test_short_name_unchanged(self):
        assert safe_path_component("simple") == "simple"

    def test_short_name_with_spaces_unchanged(self):
        assert safe_path_component("my file") == "my file"

    def test_long_name_truncated_and_hashed(self):
        long_name = "a" * 300
        result = safe_path_component(long_name)
        assert len(result.encode("utf-8")) <= 255
        assert "_" in result

    def test_distinct_long_names_yield_distinct_components(self):
        a = safe_path_component("a" * 300)
        b = safe_path_component("b" * 300)
        assert a != b

    def test_identical_long_names_are_stable(self):
        long = "x" * 300
        assert safe_path_component(long) == safe_path_component(long)

    def test_custom_max_bytes(self):
        result = safe_path_component("hello world long name", max_bytes=30)
        assert len(result.encode("utf-8")) <= 30

    def test_unicode_at_boundary_does_not_crash(self):
        name = "é" * 300
        result = safe_path_component(name)
        assert len(result.encode("utf-8")) <= 255

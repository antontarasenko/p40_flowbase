"""Tests for ``Composite.expected_files``: the documented file index.

Covers the two consumers and the split between them: ``readme.html`` keeps
the declared globs verbatim (deterministic), ``meta.json`` expands them to
the actual matched filenames (runtime), and the coverage checks
(``AllExpectedFilesPresent`` / ``NoUnindexedFiles``) enforce the index for
auto-built ``Composite`` objects only.
"""

import json
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import pytest

import p40_flowbase as fb
from p40_flowbase import checks as ck
from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.formats import CompositeFormat


class _V(Enum):
    V1 = DataObjectVersion(id="ef_v1", name="v1", description="expected_files tests")


_INDEX = (
    fb.FileSpec(
        "report.md",
        "Top-level human summary.",
    ),
    fb.FileSpec(
        "data/**/*.csv",
        "Any CSV export, at any depth under data/.",
    ),
)


class _Built(fb.Composite):
    """Auto-built Composite that writes a known file tree in ``_make``."""

    id: ClassVar[str] = "ef_built"
    description: ClassVar[str] = "Auto-built composite fixture"
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
    expected_files: ClassVar[tuple[fb.FileSpec, ...]] = _INDEX

    #: Files created by ``_make``; overridden per-test to vary coverage.
    _tree: ClassVar[tuple[str, ...]] = (
        "report.md",
        "data/2026/a.csv",
        "data/b.csv",
    )

    @override
    def _make(self) -> None:
        files_dir = self.path_to_format(CompositeFormat.FILES)
        for rel in self._tree:
            path = files_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"content of {rel}")


def _meta_optional(obj: fb.Composite) -> dict[str, Any]:
    obj.make(replace=True)
    meta = json.loads(obj.path_to_meta.read_text())
    return meta["optional"]


@pytest.mark.usefixtures("test_local_data")
class TestReadmeKeepsGlobs:
    def test_names_and_descriptions_rendered_verbatim(self) -> None:
        html = _Built(_V.V1).readme_html()
        assert "Contents" in html
        assert "report.md" in html
        assert "data/**/*.csv" in html  # glob kept, NOT expanded
        assert "Any CSV export, at any depth under data/." in html

    def test_glob_marked_as_pattern(self) -> None:
        html = _Built(_V.V1).readme_html()
        assert 'class="tag">pattern' in html  # only on the glob row

    def test_readme_does_not_expand(self) -> None:
        # readme is deterministic: no actual filenames leak in.
        html = _Built(_V.V1).readme_html()
        assert "a.csv" not in html
        assert "data/b.csv" not in html


@pytest.mark.usefixtures("test_local_data")
class TestMetaExpandsGlobs:
    def test_specs_expand_to_actual_files(self) -> None:
        opt = _meta_optional(_Built(_V.V1))
        by_name = {e["name"]: e for e in opt["expected_files"]}
        assert by_name["report.md"]["matches"] == ["report.md"]
        assert by_name["report.md"]["is_glob"] is False
        assert by_name["data/**/*.csv"]["is_glob"] is True
        assert by_name["data/**/*.csv"]["matches"] == ["data/2026/a.csv", "data/b.csv"]

    def test_unindexed_lists_uncovered_files(self) -> None:
        class _Extra(_Built):
            id: ClassVar[str] = "ef_extra"
            _tree: ClassVar[tuple[str, ...]] = (*_Built._tree, "stray.txt")

        opt = _meta_optional(_Extra(_V.V1))
        assert opt["unindexed"] == ["stray.txt"]


@pytest.mark.usefixtures("test_local_data")
class TestCoverageChecks:
    def test_all_present_passes_when_every_spec_matches(self) -> None:
        class _Ok(_Built):
            id: ClassVar[str] = "ef_ok"
            checks: ClassVar[tuple[fb.Check, ...]] = (ck.AllExpectedFilesPresent(),)

        _Ok(_V.V1).make(replace=True)  # no raise

    def test_all_present_fails_on_missing_spec(self) -> None:
        class _Missing(_Built):
            id: ClassVar[str] = "ef_missing"
            _tree: ClassVar[tuple[str, ...]] = ("report.md",)  # no CSV
            checks: ClassVar[tuple[fb.Check, ...]] = (ck.AllExpectedFilesPresent(),)

        with pytest.raises(ck.CheckFailedError, match=r"data/\*\*/\*\.csv"):
            _Missing(_V.V1).make(replace=True)

    def test_no_unindexed_fails_on_stray_file(self) -> None:
        class _Stray(_Built):
            id: ClassVar[str] = "ef_stray"
            _tree: ClassVar[tuple[str, ...]] = (*_Built._tree, "stray.txt")
            checks: ClassVar[tuple[fb.Check, ...]] = (ck.NoUnindexedFiles(),)

        with pytest.raises(ck.CheckFailedError, match=r"stray\.txt"):
            _Stray(_V.V1).make(replace=True)

    def test_coverage_check_rejects_manual_composite(self) -> None:
        class _Manual(fb.ManualComposite):
            id: ClassVar[str] = "ef_manual"
            description: ClassVar[str] = "."
            supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)
            expected_files: ClassVar[tuple[fb.FileSpec, ...]] = _INDEX
            checks: ClassVar[tuple[fb.Check, ...]] = (ck.AllExpectedFilesPresent(),)

        with pytest.raises(TypeError, match="does not apply to ManualComposite"):
            _Manual(_V.V1).make()

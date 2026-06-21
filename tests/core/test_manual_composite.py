"""Tests for ``ManualComposite``: the hand-uploaded ``Composite`` variant.

Asserts the four behaviors that set it apart from a plain ``Composite``:
idempotent ``make``, neutralized ``replace``, a ``convert`` that never
creates side formats, and a ``delete`` that refuses to run.
"""

from enum import Enum
from typing import ClassVar

import pytest

import p40_flowbase as fb
from p40_flowbase.core.base import DataObjectVersion
from p40_flowbase.core.formats import CompositeFormat


class _V(Enum):
    V1 = DataObjectVersion(id="mc_v1", name="v1", description="manual composite tests")


class _Manual(fb.ManualComposite):
    id: ClassVar[str] = "mc_manual"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.V1,)


def _add_file(obj: _Manual, name: str, body: str) -> None:
    files_dir = obj.path_to_format(CompositeFormat.FILES)
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / name).write_text(body)


def test_make_creates_empty_files_dir(test_local_data) -> None:
    obj = _Manual(_V.V1)
    obj.make()
    assert obj.path_to_format(CompositeFormat.FILES).is_dir()
    assert obj.exists()


def test_make_is_idempotent_and_preserves_hand_added_files(test_local_data) -> None:
    obj = _Manual(_V.V1)
    obj.make()
    _add_file(obj, "raw.txt", "hand-uploaded")

    # A second make() must not wipe the directory it already populated.
    obj.make()
    assert (obj.path_to_format(CompositeFormat.FILES) / "raw.txt").read_text() == (
        "hand-uploaded"
    )


def test_replace_is_neutralized(test_local_data) -> None:
    obj = _Manual(_V.V1)
    obj.make()
    _add_file(obj, "raw.txt", "hand-uploaded")

    # replace=True would normally delete() then rebuild; here it must be
    # a warning-only no-op that keeps the uploaded file in place.
    obj.make(replace=True)
    assert (obj.path_to_format(CompositeFormat.FILES) / "raw.txt").read_text() == (
        "hand-uploaded"
    )


@pytest.mark.parametrize("fmt", [CompositeFormat.ZIP, CompositeFormat.TAR_ZST])
def test_convert_creates_no_side_formats(test_local_data, fmt: CompositeFormat) -> None:
    obj = _Manual(_V.V1)
    obj.make()
    _add_file(obj, "raw.txt", "hand-uploaded")

    obj.convert(fmt)
    obj.convert()  # "all formats" shortcut must also be a no-op
    assert not obj.path_to_format(fmt).exists()


def test_delete_refuses(test_local_data) -> None:
    obj = _Manual(_V.V1)
    obj.make()
    _add_file(obj, "raw.txt", "hand-uploaded")

    with pytest.raises(RuntimeError, match="Refusing to delete"):
        obj.delete()
    assert obj.exists()


def test_is_composite_for_checks(test_local_data) -> None:
    # Composite-scoped checks (e.g. NoEmptyFiles) must accept it.
    assert isinstance(_Manual(_V.V1), fb.Composite)

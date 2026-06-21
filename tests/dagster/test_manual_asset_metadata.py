"""``ManualComposite`` assets carry a definition-time not-rebuildable mark.

``assets_from_classes`` stamps a ``rebuildable=false`` tag plus
descriptive metadata on any class whose ``asset_rebuildable`` is
``False`` (set by ``ManualComposite``), so the Dagster UI flags that the
data is managed out-of-band. A plain ``Composite`` stays unmarked.
"""

from enum import Enum
from typing import ClassVar

import dagster as dg

import p40_flowbase as fb
from p40_flowbase.core.base import DataObjectVersion


class _V(Enum):
    MAIN = DataObjectVersion(id="main", name="main", description="manual asset test")


@fb.asset(group="uploads")
class _ManualAsset(fb.ManualComposite):
    id: ClassVar[str] = "manual_asset_meta"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.MAIN,)


@fb.asset(group="built")
class _PlainComposite(fb.Composite):
    id: ClassVar[str] = "plain_composite_meta"
    description: ClassVar[str] = "."
    supported_versions: ClassVar[tuple[Enum, ...]] = (_V.MAIN,)


def _build(cls: type) -> dg.AssetsDefinition:
    [asset_def] = fb.assets_from_classes(
        [cls],
        partitions_def=fb.partitions_from_versions((_V.MAIN,)),
        version_enum_class=_V,
    )
    return asset_def


def test_manual_asset_marked_not_rebuildable() -> None:
    asset_def = _build(_ManualAsset)
    key = dg.AssetKey("manual_asset_meta")

    assert asset_def.tags_by_key[key].get("rebuildable") == "false"
    meta = asset_def.metadata_by_key[key]
    # Dagster may keep the raw value or wrap it in a MetadataValue.
    rebuildable = meta["rebuildable"]
    assert getattr(rebuildable, "value", rebuildable) is False
    assert "lifecycle" in meta


def test_plain_composite_is_unmarked() -> None:
    asset_def = _build(_PlainComposite)
    key = dg.AssetKey("plain_composite_meta")

    assert "rebuildable" not in asset_def.tags_by_key[key]
    assert "rebuildable" not in asset_def.metadata_by_key[key]

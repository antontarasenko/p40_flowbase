"""``ManualContextFiles``: hand-authored project context for the whole module."""

from enum import Enum
from typing import ClassVar

import p40_flowbase as fb
from p40_flowbase import checks as ck

from p40_weather.objects.versions import SUPPORTED_VERSIONS


@fb.asset()
class ManualContextFiles(fb.ManualComposite):
    """Hand-uploaded project context for the whole module.

    A ``ManualComposite`` holding the module author's description of the
    project: what the pipeline does, where the data comes from, and any
    caveats. ``make`` only ensures an empty ``.files`` directory exists;
    nothing in the repo regenerates it. The content is added by hand
    (copied in, or pulled from object storage out-of-band), so the
    object materializes empty and you populate it yourself.

    Organize ``.files`` as an **append-only series of dated entries**,
    one subfolder per update::

        <YYMMDD>_<title>/

    e.g. ``260614_project_description/`` then ``260621_status_update/``.
    Each update gets its own subfolder; older entries are never
    rewritten, so ``.files`` reads as a chronological log of the module's
    context.

    Because it is a ``ManualComposite`` the curated history cannot be
    silently lost: ``delete`` raises, ``replace`` is a no-op, and
    ``convert`` is blocked so ``.files`` stays the only format (a
    ``.zip`` snapshot would drift, since the object is never rebuilt).
    In the Dagster graph it is a root asset tagged ``rebuildable=false``.
    """

    id: ClassVar[str] = "manual_context_files"
    description: ClassVar[str] = (
        "Hand-uploaded project description/context for the module."
    )
    supported_versions: ClassVar[tuple[Enum, ...]] = SUPPORTED_VERSIONS
    # Documents the dated-entry convention for a human reader (rendered in
    # readme.html). Globs are illustrative, not exhaustive: the index just
    # explains what belongs in each <YYMMDD>_<title>/ folder.
    expected_files: ClassVar[tuple[fb.FileSpec, ...]] = (
        fb.FileSpec(
            "*/project_description.md",
            "Per dated entry: the main context note for that update.",
        ),
        fb.FileSpec(
            "**/*.md",
            "Any Markdown notes within a dated entry.",
        ),
        fb.FileSpec(
            "**/*.png",
            "Screenshots or diagrams referenced by the notes.",
        ),
    )
    # Populated out-of-band, so make() must succeed on an empty directory;
    # only guard against truncated / 0-byte uploads. No coverage checks:
    # .files is empty at make time, so AllExpectedFilesPresent /
    # NoUnindexedFiles cannot be evaluated (and would be rejected here).
    checks: ClassVar[tuple[fb.Check, ...]] = (ck.NoEmptyFiles(),)

"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import importlib.resources
import pathlib
import shutil
import subprocess
import tempfile
from abc import abstractmethod
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

from jinja2 import (
    Environment,
    FileSystemLoader,
)

from p40_flowbase.core.base import (
    DataObject,
    resolve_anchor_package,
)
from p40_flowbase.core.formats import DocumentFormat
from p40_flowbase.dagster.wiring import DagsterAssetWiring


class Document(DataObject, DagsterAssetWiring):
    """Markdown-first document data object rendered from a Jinja template.

    Convention (zero-boilerplate template lookup)
    ---------------------------------------------
    Define a new ``Document`` with three pieces:

    1. A ``Document`` subclass with ``id``, ``description``,
       ``supported_versions``.
    2. An implementation of ``_make_data(self) -> None`` that populates
       ``self.data``.
    3. A Jinja+Markdown template at
       ``<your_pkg>/resources/templates/documents/<id>.md.jinja``.

    Calling ``MyDoc(version).make()`` then renders the template with
    ``self.data`` and writes the resulting Markdown as the master file.
    Convert to PDF / HTML / Beamer-PDF via ``convert(fmt)``.

    Supported formats
    -----------------
    MD (master, default), PDF, HTML, BEAMER_PDF (all conversions via
    ``pandoc``).

    Attributes
    ----------
    template_package:
        Anchor Python package for the template lookup. Defaults to the
        top-level package of the subclass module (e.g. ``their_pkg``
        for ``their_pkg.objects.docs.MyDoc``). Override for nested
        layouts where templates live in a different package.
    template_subpath:
        Directory inside ``template_package`` holding ``*.md.jinja``
        files. Defaults to ``"resources/templates/documents"``.
    template_name:
        Template filename. Defaults to ``f"{id}.md.jinja"``. Override
        only if the file does not match the convention.
    data:
        Dictionary of variables passed into the Jinja render. Populate
        in ``_make_data``.
    """

    make_format: ClassVar[DocumentFormat] = DocumentFormat.MD  # pyright: ignore[reportIncompatibleVariableOverride]
    template_package: ClassVar[str | None] = None
    template_subpath: ClassVar[str] = "resources/templates/documents"
    template_name: ClassVar[str | None] = None
    data: dict[str, Any]

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self.data = {}

    @abstractmethod
    def _make_data(self) -> None:
        """Populate ``self.data`` for the Jinja render.

        Must be implemented by subclasses. Called by ``_make`` before
        the template is rendered.
        """

    def _resolve_template_name(self) -> str:
        return self.template_name or f"{self.id}.md.jinja"

    def _render_template(self) -> pathlib.Path:
        """Render the Jinja template with ``self.data``.

        :returns: Path to the rendered ``.md`` inside a temporary directory.
        :rtype: pathlib.Path
        """
        temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="jinja_template_"))
        template_filename = self._resolve_template_name()

        try:
            anchor_pkg = resolve_anchor_package(self)
            template_root = importlib.resources.files(anchor_pkg)
            template_content = (
                template_root.joinpath(self.template_subpath, template_filename)
                .read_text()
            )

            template_path = temp_dir / template_filename
            template_path.write_text(template_content)

            env = Environment(loader=FileSystemLoader(str(temp_dir)), autoescape=False)  # noqa: S701  # markdown/LaTeX templates, not HTML
            template_obj = env.get_template(template_filename)

            rendered_md = template_obj.render(**self.data)

            output_path = temp_dir / "rendered.md"
            output_path.write_text(rendered_md)

            return output_path
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    @override
    def _make(self) -> None:
        """Populate ``self.data`` and render the master Markdown file."""
        self._make_data()
        rendered_path = self._render_template()

        self.local_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(rendered_path, self.path_to_format(DocumentFormat.MD))

        shutil.rmtree(rendered_path.parent, ignore_errors=True)

    def _convert_to_pdf(self) -> None:
        """Convert md to pdf using pandoc."""
        md_path = self.path_to_format(DocumentFormat.MD)
        pdf_path = self.path_to_format(DocumentFormat.PDF)
        subprocess.run(
            ["pandoc", str(md_path), "-o", str(pdf_path)],
            check=True,
        )

    def _convert_to_html(self) -> None:
        """Convert md to html using pandoc."""
        md_path = self.path_to_format(DocumentFormat.MD)
        html_path = self.path_to_format(DocumentFormat.HTML)
        subprocess.run(
            ["pandoc", str(md_path), "-o", str(html_path)],
            check=True,
        )

    def _convert_to_beamer_pdf(self) -> None:
        """Convert md to beamer pdf using pandoc."""
        md_path = self.path_to_format(DocumentFormat.MD)
        beamer_pdf_path = self.path_to_format(DocumentFormat.BEAMER_PDF)
        subprocess.run(
            [
                "pandoc",
                str(md_path),
                "--to=beamer",
                "--output=" + str(beamer_pdf_path),
            ],
            check=True,
        )

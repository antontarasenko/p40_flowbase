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
from typing import Dict

from jinja2 import (
    Environment,
    FileSystemLoader,
)

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import DocumentFormat
from p40_flowbase.logging import logger


class DocumentDataObject(DataObject):
    """Base class for Jinja-based document data objects.

    Document objects render Jinja templates with data.
    Supported formats:
        - MD: Markdown document (default)
        - PDF: PDF document (via pandoc)
        - HTML: HTML document (via pandoc)
        - BEAMER_PDF: Beamer presentation PDF (via pandoc)

    Attributes:
        template: Name of the Jinja template file.
        template_package: Package containing the template (for importlib.resources).
        data: Dictionary of data to render into the template.

    Subclasses must implement _make_data() to populate self.data.
    """

    make_format: DocumentFormat = DocumentFormat.MD
    template: str
    template_package: str = "p40_flowbase.templates"
    data: Dict

    def __init__(self, version):
        super().__init__(version)
        self.data = {}

    @abstractmethod
    def _make_data(self) -> None:
        """Create and populate self.data dict.

        Must be implemented by subclasses to prepare template data.
        """
        pass

    def _render_template(self) -> pathlib.Path:
        """Render Jinja template with self.data and return path to rendered md."""
        temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="jinja_template_"))

        try:
            template_package = importlib.resources.files(self.template_package)
            template_content = template_package.joinpath(self.template).read_text()

            template_path = temp_dir / self.template
            template_path.write_text(template_content)

            env = Environment(loader=FileSystemLoader(str(temp_dir)))
            template_obj = env.get_template(self.template)

            rendered_md = template_obj.render(**self.data)

            output_path = temp_dir / "rendered.md"
            output_path.write_text(rendered_md)

            return output_path
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _make_default(self) -> None:
        """Create and save the default format (md)."""
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
        logger.info(f"Converted to PDF: {pdf_path}")

    def _convert_to_html(self) -> None:
        """Convert md to html using pandoc."""
        md_path = self.path_to_format(DocumentFormat.MD)
        html_path = self.path_to_format(DocumentFormat.HTML)
        subprocess.run(
            ["pandoc", str(md_path), "-o", str(html_path)],
            check=True,
        )
        logger.info(f"Converted to HTML: {html_path}")

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
        logger.info(f"Converted to Beamer PDF: {beamer_pdf_path}")

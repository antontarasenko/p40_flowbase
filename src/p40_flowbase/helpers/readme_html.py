"""Render the package-shipped ``<kind>.readme.html.jinja`` README template.

``PackageLoader`` is used so ``{% extends %}`` resolves (``table`` extends
``base``); ``autoescape`` is on because the output is HTML.
"""

from typing import Any

import jinja2

_TEMPLATE_PACKAGE = "p40_flowbase"
_TEMPLATE_SUBPATH = "resources/templates/readme"


def render_readme_html(*, kind: str, context: dict[str, Any]) -> str:
    """Render ``<kind>.readme.html.jinja`` with ``context``."""
    env = jinja2.Environment(
        loader=jinja2.PackageLoader(_TEMPLATE_PACKAGE, _TEMPLATE_SUBPATH),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(f"{kind}.readme.html.jinja")
    return template.render(**context)

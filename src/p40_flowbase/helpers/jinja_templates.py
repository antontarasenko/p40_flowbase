"""Jinja-from-package template renderer.

Loads any ``.jinja`` template file shipped as package data and renders
it with the supplied keyword arguments. Used by:

- ``Table.make_via_sql_template`` to render ``.sql.jinja`` files under
  ``<pkg>/resources/templates/tables/``.
- ``Document._render_template`` to render ``.md.jinja`` files under
  ``<pkg>/resources/templates/documents/``.
- Any downstream code that needs a one-call Jinja-from-resource render
  (e.g. agent prompt templates under
  ``<pkg>/resources/templates/prompts/``).

The function is template-format-agnostic — caller picks the file
extension and the subpath.
"""

import importlib.resources
from typing import Any

import jinja2


def render_jinja_template(
    template_name: str,
    *,
    package: str,
    subpath: str = "resources/templates/tables",
    **template_vars: Any,
) -> str:
    """Render ``<package>/<subpath>/<template_name>`` with Jinja2.

    :param template_name: Template file name, e.g.
        ``"widgets.sql.jinja"`` or ``"my_doc.md.jinja"``.
    :param package: Anchor Python package; the loader walks
        ``importlib.resources.files(package).joinpath(subpath, template_name)``.
        ``subpath`` does **not** require ``__init__.py`` files — only
        ``package`` itself must be a real Python package.
    :param subpath: Directory inside ``package`` holding the templates.
        Defaults to the SQL convention; pass
        ``"resources/templates/documents"`` or
        ``"resources/templates/prompts"`` for those families.
    :param template_vars: Variables passed into the Jinja render call.
    :returns: Rendered template text.
    """
    root = importlib.resources.files(package)
    template_content = root.joinpath(subpath, template_name).read_text()
    env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=False)  # noqa: S701
    template = env.from_string(template_content)
    return template.render(**template_vars)

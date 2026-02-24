"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import importlib.resources
from typing import (
    Any,
)

import jinja2


def render_prompt_template(
    template_name: str,
    project_package: str | None = None,
    **kwargs: Any,
) -> str:
    """Render a Jinja template from a prompts directory.

    Searches for the template in the project package first (if provided),
    then falls back to p40_flowbase.prompts.

    Args:
        template_name: Name of the template file in the prompts directory.
        project_package: Package path containing prompts (e.g., "myproject.prompts").
            If provided, searches here first before falling back to base package.
        **kwargs: Variables to pass to the template.

    Returns:
        Rendered template as string.

    Example:
        rendered = render_prompt_template(
            template_name="extraction.md.jinja",
            project_package="myproject.prompts",
            data_format="json",
        )
    """
    template_content = None

    if project_package:
        try:
            prompts_package = importlib.resources.files(project_package)
            template_content = prompts_package.joinpath(template_name).read_text()
        except (ModuleNotFoundError, FileNotFoundError):
            pass

    if template_content is None:
        try:
            base_prompts = importlib.resources.files("p40_flowbase.prompts")
            template_content = base_prompts.joinpath(template_name).read_text()
        except (ModuleNotFoundError, FileNotFoundError) as e:
            raise FileNotFoundError(
                f"Template '{template_name}' not found in "
                f"{project_package or 'project'} or p40_flowbase.prompts"
            ) from e

    env = jinja2.Environment(loader=jinja2.BaseLoader())
    template = env.from_string(template_content)

    return template.render(**kwargs)

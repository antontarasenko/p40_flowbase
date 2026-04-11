"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import asyncio
from typing import Annotated

import typer

from p40_flowbase.logging import logger
from p40_flowbase.manager.utils import (
    format_versions_help,
    get_version_enum,
)


def create_object_app(
    obj_class: type,
    local_data: str,
) -> typer.Typer:
    """Create a Typer app for an object class with standard commands.

    Generates commands for:
    - make: Create the data object
    - convert: Convert to all formats
    - populate: Populate requests (if HTTP/LLM mixin present)
    - execute: Execute pending requests (if HTTP/LLM mixin present)
    - retry: Retry failed requests (if HTTP/LLM mixin present)

    Args:
        obj_class: The data object class.
        local_data: Base path for data storage.

    Returns:
        Typer app with appropriate commands.
    """
    epilog = format_versions_help(
        obj_class=obj_class,
        local_data=local_data,
    )

    object_app = typer.Typer(
        help=obj_class.description,
        epilog=epilog,
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    @object_app.command(epilog=epilog)
    def make(
        version: Annotated[str, typer.Option("--version", help="Version to create")],
    ) -> None:
        """Create the data object."""
        version_enum = get_version_enum(obj_class, version)
        obj = obj_class(version_enum)

        logger.info(f"Making {obj_class.id} (version: {version})")

        if hasattr(obj, "make_async"):
            asyncio.run(obj.make_async(replace=False))
        else:
            obj.make(replace=False)

        logger.info(f"Successfully created {obj_class.id}")

    @object_app.command(name="convert", epilog=epilog)
    def convert_cmd(
        version: Annotated[str, typer.Option("--version", help="Version to convert")],
    ) -> None:
        """Convert the data object to all formats."""
        version_enum = get_version_enum(obj_class, version)
        obj = obj_class(version_enum)

        logger.info(f"Saving all formats for {obj_class.id} (version: {version})")
        obj.convert(replace=False)
        logger.info(f"Successfully saved {obj_class.id}")

    @object_app.command(name="delete", epilog=epilog)
    def delete_cmd(
        version: Annotated[str, typer.Option("--version", help="Version to delete")],
    ) -> None:
        """Delete the data object and all its formats."""
        version_enum = get_version_enum(obj_class, version)
        obj = obj_class(version_enum)

        logger.info(f"Deleting {obj_class.id} (version: {version})")
        obj.delete()
        logger.info(f"Successfully deleted {obj_class.id} (version: {version})")

    has_requests = (
        hasattr(obj_class, "_populate_http_requests")
        or hasattr(obj_class, "_populate_llm_requests")
        or hasattr(obj_class, "_populate_agent_tasks")
    )

    obj_rate_limit = getattr(obj_class, "default_rate_limit", 5.0)
    obj_rate_period = getattr(obj_class, "default_rate_period", 1.0)

    if has_requests:
        @object_app.command(name="populate", epilog=epilog)
        def populate(
            version: Annotated[
                str,
                typer.Option("--version", help="Version to populate requests for"),
            ],
        ) -> None:
            """Populate requests for this version."""
            version_enum = get_version_enum(obj_class, version)
            obj = obj_class(version_enum)

            logger.info(
                f"Populating requests for {obj_class.id} (version: {version})"
            )
            group_id = asyncio.run(obj.populate())
            logger.info(
                f"Successfully populated requests for {obj_class.id}, "
                f"group_id: {group_id}"
            )

    if has_requests:
        @object_app.command(name="execute", epilog=epilog)
        def execute_cmd(
            version: Annotated[
                str,
                typer.Option("--version", help="Version to execute requests for"),
            ],
            rate_limit: Annotated[
                float,
                typer.Option("--rate-limit", help="Maximum requests per rate period"),
            ] = obj_rate_limit,
            rate_period: Annotated[
                float,
                typer.Option("--rate-period", help="Rate period in seconds"),
            ] = obj_rate_period,
        ) -> None:
            """Execute pending requests."""
            version_enum = get_version_enum(obj_class, version)
            obj = obj_class(version_enum)

            logger.info(
                f"Executing pending requests for {obj_class.id} (version: {version})"
            )
            asyncio.run(
                obj.execute(
                    rate_limit=rate_limit,
                    rate_period=rate_period,
                )
            )
            logger.info(f"Successfully executed requests for {obj_class.id}")

    if has_requests:
        @object_app.command(name="retry", epilog=epilog)
        def retry_cmd(
            version: Annotated[
                str,
                typer.Option(
                    "--version",
                    help="Version to retry failed requests for",
                ),
            ],
            rate_limit: Annotated[
                float,
                typer.Option("--rate-limit", help="Maximum requests per rate period"),
            ] = obj_rate_limit,
            rate_period: Annotated[
                float,
                typer.Option("--rate-period", help="Rate period in seconds"),
            ] = obj_rate_period,
        ) -> None:
            """Retry failed requests."""
            version_enum = get_version_enum(obj_class, version)
            obj = obj_class(version_enum)

            logger.info(
                f"Retrying failed requests for {obj_class.id} (version: {version})"
            )
            asyncio.run(
                obj.retry(
                    rate_limit=rate_limit,
                    rate_period=rate_period,
                )
            )
            logger.info(f"Successfully retried requests for {obj_class.id}")

    has_lane_step = hasattr(obj_class, "_populate_lane_step")

    if has_lane_step:
        @object_app.command(name="execute-graph", epilog=epilog)
        def execute_graph_cmd(
            version: Annotated[
                str,
                typer.Option("--version", help="Version to execute graph for"),
            ],
            lanes: Annotated[
                str,
                typer.Option(
                    "--lanes",
                    help="Comma-separated lane identifiers",
                ),
            ],
            num_steps: Annotated[
                int,
                typer.Option("--num-steps", help="Number of sequential steps per lane"),
            ],
            rate_limit: Annotated[
                float,
                typer.Option("--rate-limit", help="Maximum requests per rate period"),
            ] = obj_rate_limit,
            rate_period: Annotated[
                float,
                typer.Option("--rate-period", help="Rate period in seconds"),
            ] = obj_rate_period,
            max_retries: Annotated[
                int,
                typer.Option("--max-retries", help="Maximum retry attempts per step"),
            ] = 1,
        ) -> None:
            """Execute a parallel-lane, sequential-step graph."""
            version_enum = get_version_enum(obj_class, version)
            obj = obj_class(version_enum)

            lane_list = [lane.strip() for lane in lanes.split(",") if lane.strip()]

            logger.info(
                f"Executing graph for {obj_class.id} (version: {version}), "
                f"{len(lane_list)} lanes, {num_steps} steps"
            )
            results = asyncio.run(
                obj.execute_graph(
                    lanes=lane_list,
                    num_steps=num_steps,
                    rate_limit=rate_limit,
                    rate_period=rate_period,
                    max_retries=max_retries,
                )
            )
            total_results = sum(
                len(step_results)
                for lane_results in results.values()
                for step_results in lane_results
            )
            logger.info(
                f"Successfully executed graph for {obj_class.id}: "
                f"{len(results)} lanes, {total_results} total results"
            )

    return object_app

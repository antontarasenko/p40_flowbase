"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Dict,
    Optional,
    Type,
)

import typer
from typing_extensions import Annotated

from p40_flowbase.core.base import DataObject
from p40_flowbase.llm.mixin import LLMRequestsDBMixin
from p40_flowbase.manager.commands import create_object_app
from p40_flowbase.manager.utils import (
    check_object_exists,
    get_existing_formats,
)


class BaseDataObjectManager(ABC):
    """Base class for data object managers.

    Subclasses must define:
    - OBJECTS: Dict mapping object IDs to DataObject classes
    - app_name: Name for the CLI application
    - app_help: Help text for the CLI application
    - data_local_tmp: Path to the data storage directory

    Example:
        class MyManager(BaseDataObjectManager):
            OBJECTS = {
                MySample.id: MySample,
                MyTable.id: MyTable,
            }
            app_name = "my_manager"
            app_help = "Manage my data objects"
            data_local_tmp = "/path/to/data"

        if __name__ == "__main__":
            manager = MyManager()
            manager.run()
    """

    OBJECTS: Dict[str, Type[DataObject]] = {}
    app_name: str = "data_manager"
    app_help: str = "Manage data objects"

    @property
    @abstractmethod
    def data_local_tmp(self) -> str:
        """Return the path to the data storage directory."""
        ...

    @property
    def anthropic_api_key(self) -> Optional[str]:
        """Return Anthropic API key. Override in subclass to provide key."""
        return None

    @property
    def google_api_key(self) -> Optional[str]:
        """Return Google API key. Override in subclass to provide key."""
        return None

    @property
    def openai_api_key(self) -> Optional[str]:
        """Return OpenAI API key. Override in subclass to provide key."""
        return None

    def __init__(self):
        """Initialize the manager with a Typer app."""
        DataObject.set_data_local_tmp(self.data_local_tmp)
        LLMRequestsDBMixin.set_api_keys(
            anthropic_api_key=self.anthropic_api_key,
            google_api_key=self.google_api_key,
            openai_api_key=self.openai_api_key,
        )

        self.app = typer.Typer(
            help=self.app_help,
            no_args_is_help=True,
            context_settings={"help_option_names": ["-h", "--help"]},
        )

        self._setup_main_callback()
        self._register_object_apps()
        self.configure_styles()

    def _setup_main_callback(self) -> None:
        """Set up the main callback with --list-objects option."""

        @self.app.callback(invoke_without_command=True)
        def main_callback(
            ctx: typer.Context,
            list_objects: Annotated[
                bool,
                typer.Option(
                    "--list-objects",
                    help="Show tree of all objects with their versions and formats",
                ),
            ] = False,
        ):
            if list_objects:
                self._list_objects()
                raise typer.Exit()

    def _list_objects(self) -> None:
        """Display tree of all objects with versions and formats."""
        for object_id, object_class in self.OBJECTS.items():
            object_id_bold = typer.style(object_id, bold=True)
            typer.echo(f"{object_id_bold} - {object_class.description}")

            for version_enum in object_class.supported_versions:
                version_id = version_enum.value.id
                version_desc = version_enum.value.description
                exists = check_object_exists(
                    object_id=object_id,
                    version=version_id,
                    data_local_tmp=self.data_local_tmp,
                )
                marker = "✓" if exists else "○"

                if exists:
                    formats = get_existing_formats(
                        object_id=object_id,
                        version=version_id,
                        data_local_tmp=self.data_local_tmp,
                    )
                else:
                    formats = []

                if formats:
                    formats_str = typer.style(f" [{' '.join(formats)}]", bold=True)
                else:
                    formats_str = ""

                version_id_bold = typer.style(version_id, bold=True)
                typer.echo(
                    f"  {marker} {version_id_bold}{formats_str} - {version_desc}"
                )

    def _register_object_apps(self) -> None:
        """Register Typer apps for each object class."""
        for object_id, object_class in self.OBJECTS.items():
            object_app = create_object_app(
                obj_class=object_class,
                data_local_tmp=self.data_local_tmp,
            )
            self.app.add_typer(object_app, name=object_id)

    def configure_styles(self) -> None:
        """Configure matplotlib styles.

        Override this method to apply custom styles.

        Example:
            def configure_styles(self) -> None:
                from p40_flowbase.styles import apply_style
                apply_style("style_1")
        """
        pass

    def run(self) -> None:
        """Run the CLI application."""
        self.app()

"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import pathlib

import typer


def check_object_exists(
    object_id: str,
    version: str,
    local_data: str,
) -> bool:
    """Check if a data object version exists on disk.

    Args:
        object_id: The data object identifier.
        version: The version identifier.
        local_data: Base path for data storage.

    Returns:
        True if the object directory exists, False otherwise.
    """
    object_stem = f"{object_id}-{version}"
    object_dir = pathlib.Path(local_data) / object_stem
    return object_dir.exists()


def get_existing_formats(
    object_id: str,
    version: str,
    local_data: str,
) -> list[str]:
    """Get list of existing format extensions for a data object version.

    Args:
        object_id: The data object identifier.
        version: The version identifier.
        local_data: Base path for data storage.

    Returns:
        Sorted list of file extensions (without dots) found in the object directory.
    """
    object_stem = f"{object_id}-{version}"
    object_dir = pathlib.Path(local_data) / object_stem
    if not object_dir.exists():
        return []

    formats = []
    prefix = f"{object_stem}."
    for file in object_dir.iterdir():
        if file.is_file():
            if file.name.startswith(prefix):
                ext = file.name[len(prefix):]
            else:
                ext = file.suffix.lstrip(".")
            if ext:
                formats.append(ext)

    return sorted(set(formats))


def get_version_enum(object_class: type, version_id: str):
    """Get the version enum member for a given version ID.

    Args:
        object_class: The data object class.
        version_id: The version identifier string.

    Returns:
        The matching version enum member.

    Raises:
        typer.BadParameter: If version_id is not found in supported_versions.
    """
    for version_enum in object_class.supported_versions:
        if version_enum.value.id == version_id:
            return version_enum
    supported = [v.value.id for v in object_class.supported_versions]
    raise typer.BadParameter(
        f"Version '{version_id}' not found for {object_class.__name__}. "
        f"Supported versions: {supported}"
    )


def format_versions_help(
    obj_class: type,
    local_data: str,
) -> str:
    """Generate versions help text for an object class.

    Args:
        obj_class: The data object class.
        local_data: Base path for data storage.

    Returns:
        Formatted help text showing supported versions with markers and formats.
    """
    epilog_lines = ["\nSupported versions:"]

    for version_enum in obj_class.supported_versions:
        version_id = version_enum.value.id
        version_desc = version_enum.value.description

        exists = check_object_exists(
            object_id=obj_class.id,
            version=version_id,
            local_data=local_data,
        )
        marker = "✓" if exists else "○"

        if exists:
            formats = get_existing_formats(
                object_id=obj_class.id,
                version=version_id,
                local_data=local_data,
            )
        else:
            formats = []

        version_id_bold = typer.style(version_id, bold=True)

        if formats:
            formats_str = " " + typer.style(f"[{' '.join(formats)}]", bold=True)
        else:
            formats_str = ""

        epilog_lines.append(
            f"  {marker} {version_id_bold}{formats_str} - {version_desc}"
        )

    return "\n".join(epilog_lines)

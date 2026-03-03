# Contributing

## Prerequisites

- Install `nix` (multi-user installation recommended)
- Enable `nix-command` and `flakes`
- Install `nix-direnv` package

## Setup

Enable dev shell via `direnv` and check for available options:

```sh
direnv allow
make help
```

## Environment

When you add a dependency to `pyproject.toml`, update the local dev environment:

```sh
uv lock
direnv reload
```

When you update dependencies in `flake.nix`, update `flake.lock`:

```sh
nix flake update
```

## Commits

Pre-commit routine:

```
black src/ tests/
ruff check src/ tests/
mypy src/
pytest
pytest --cov
coverage report
```

## Releases

1. Update the code

1. Update `CHANGELOG.md`

1. Update `flake.nix` (`scmVersionOverlay`):

    ```
    version = "1.2.3";
    ```

1. Rebuild:

    ```
    uv lock && direnv reload
    ```

1. Commit:

    ```
    git add .
    git commit -m "Release 1.2.3"
    ```

1. Tag:

    ```
    git tag 1.2.3
    ```

1. Verify:

    ```
    python -c "from p40_flowbase import __version__; print(__version__)"
    python -m setuptools_scm
    make info
    ```

1. Push:

    ```
    git push
    git push --tags
    ```

1. Release:

    ```
    make all
    ```


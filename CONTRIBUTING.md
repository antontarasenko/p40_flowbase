# Contributing

## Prerequisites

- `nix` with `nix-command` and `flakes` enabled and the `nix-direnv` package installed

## Setup

Enable dev shell via `direnv` and check for available options:

```sh
direnv allow
make help
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


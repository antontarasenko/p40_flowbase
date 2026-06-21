# p40_flowbase

[![PyPI](https://img.shields.io/pypi/v/p40-flowbase)](https://pypi.org/project/p40-flowbase/)
[![Python](https://img.shields.io/pypi/pyversions/p40-flowbase)](https://pypi.org/project/p40-flowbase/)
[![License: MIT](https://img.shields.io/pypi/l/p40-flowbase)](LICENSE)

A single-dependency data pipeline framework. You model each step of a pipeline as a `DataObject` subclass with one uniform lifecycle (`make` / `convert` / `delete`), a typed schema, declarative post-make checks. Any object becomes a partitioned, dependency-aware Dagster asset with a single decorator.

## Install

```sh
pip install p40_flowbase
```

## Documentation

- [`examples/p40_weather/`](examples/p40_weather/)
- [`CHANGELOG.md`](CHANGELOG.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md)

## License

→ [`LICENSE`](LICENSE)

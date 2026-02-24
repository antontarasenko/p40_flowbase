"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""


import pandas as pd
import pydantic as pyd

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import TableFormat
from p40_flowbase.logging import logger


class TableDataObject(DataObject):
    """Base class for tabular data objects.

    Table objects store data as pandas DataFrames.
    Supported formats:
        - PARQUET: Apache Parquet format (default)
        - CSV: Comma-separated values
        - TSV: Tab-separated values
        - MD: Markdown table
        - JSON: JSON array of records

    Attributes:
        schema: Pydantic model class defining the table schema.
    """

    make_format: TableFormat = TableFormat.PARQUET
    schema: type[pyd.BaseModel]

    def __init__(self, version):
        super().__init__(version)
        self._df: pd.DataFrame | None = None

    @property
    def pdf(self) -> pd.DataFrame:
        """Return the object as pandas DataFrame (lazy loading)."""
        if self._df is None:
            self._df = pd.read_parquet(
                self.path_to_format(TableFormat.PARQUET),
                dtype_backend="pyarrow",
            )
        return self._df

    def _convert_to_csv(self) -> None:
        """Convert parquet to csv."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        csv_path = self.path_to_format(TableFormat.CSV)
        df.to_csv(csv_path, index=False)
        logger.info(f"Converted to CSV: {csv_path}")

    def _convert_to_tsv(self) -> None:
        """Convert parquet to tsv."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        tsv_path = self.path_to_format(TableFormat.TSV)
        df.to_csv(tsv_path, sep="\t", index=False)
        logger.info(f"Converted to TSV: {tsv_path}")

    def _convert_to_md(self) -> None:
        """Convert parquet to markdown."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        md_content = df.to_markdown(index=False)
        md_path = self.path_to_format(TableFormat.MD)
        with open(md_path, "w") as f:
            f.write(md_content)
        logger.info(f"Converted to Markdown: {md_path}")

    def _convert_to_json(self) -> None:
        """Convert parquet to json."""
        df = pd.read_parquet(
            self.path_to_format(TableFormat.PARQUET),
            dtype_backend="pyarrow",
        )
        json_path = self.path_to_format(TableFormat.JSON)
        df.to_json(json_path, orient="records", indent=2)
        logger.info(f"Converted to JSON: {json_path}")

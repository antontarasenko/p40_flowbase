"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import numpy as np
import pandas as pd


def create_summary_stats_table(df: pd.DataFrame) -> pd.DataFrame:
    """Create a table with summary statistics for numerical columns.

    Args:
        df: DataFrame with data.

    Returns:
        DataFrame with summary statistics including column_name as first column.

    Example:
        stats = create_summary_stats_table(my_dataframe)
        print(stats[["column_name", "mean", "std", "min", "max"]])
    """
    sample_numeric = df.select_dtypes(include=[np.number])
    stats_df = sample_numeric.describe().T
    stats_df.insert(0, "column_name", stats_df.index)
    stats_df = stats_df.reset_index(drop=True)

    return stats_df

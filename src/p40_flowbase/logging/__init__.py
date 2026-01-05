"""Logging configuration for p40_flowbase."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("p40_flowbase")

__all__ = ["logger"]

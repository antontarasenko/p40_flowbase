"""
MIT License

Copyright (c) 2025 Anton Tarasenko
"""

import pickle
from abc import abstractmethod
from enum import Enum
from typing import (
    Any,
    ClassVar,
    override,
)

import joblib

from p40_flowbase.core.base import DataObject
from p40_flowbase.core.formats import ModelFormat


class Model(DataObject):
    """Base class for machine learning model data objects.

    Model objects store trained ML models.
    Supported formats:
        - PKL: Pickled model (default)
        - JOBLIB: Joblib serialized model

    Subclasses must implement _fit() to train and save the model.
    """

    make_format: ClassVar[ModelFormat] = ModelFormat.PKL  # pyright: ignore[reportIncompatibleVariableOverride]

    def __init__(self, version: Enum) -> None:
        super().__init__(version)
        self._model: Any | None = None

    @property
    def model(self) -> Any:
        """Return the trained model (lazy loading)."""
        if self._model is None:
            with open(self.path_to_format(ModelFormat.PKL), "rb") as f:
                self._model = pickle.load(f)  # noqa: S301  # internal cache file we wrote ourselves
        return self._model

    @abstractmethod
    def _fit(self) -> None:
        """Fit the model and save it.

        Must be implemented by subclasses to train and pickle the model.
        """

    @override
    def _make(self) -> None:
        """Create and save the default format (pkl)."""
        self._fit()

    def _convert_to_joblib(self) -> None:
        model = self.model
        joblib_path = self.path_to_format(ModelFormat.JOBLIB)
        joblib.dump(model, joblib_path)

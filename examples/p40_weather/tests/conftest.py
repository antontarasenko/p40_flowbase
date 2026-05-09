"""Test setup for p40_weather.

Sets a placeholder ``LOCAL_DATA`` env var **before** any p40_weather
import resolves ``WeatherSettings()``. The actual per-test data root
is set inside the ``local_data`` fixture in ``test_smoke.py`` via
``fb.DataObject.set_local_data(str(tmp_path))``; this just keeps the
top-of-module import in ``definitions.py`` from raising.
"""

import os

os.environ.setdefault("LOCAL_DATA", "/tmp/p40_weather_test_placeholder")

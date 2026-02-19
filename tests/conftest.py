import pytest

from p40_flowbase.core.base import DataObject


@pytest.fixture(scope="session")
def test_data_local_tmp(tmp_path_factory):
    """Set DataObject._data_local_tmp to a session-scoped temporary directory."""
    tmp_dir = tmp_path_factory.mktemp("data")
    DataObject.set_data_local_tmp(str(tmp_dir))
    return str(tmp_dir)

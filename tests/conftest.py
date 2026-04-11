import pytest

from p40_flowbase.core.base import DataObject


@pytest.fixture(scope="session")
def test_local_data(tmp_path_factory):
    """Set DataObject._local_data to a session-scoped temporary directory."""
    tmp_dir = tmp_path_factory.mktemp("data")
    DataObject.set_local_data(str(tmp_dir))
    return str(tmp_dir)

import pytest
from banlog.db import open_db


@pytest.fixture
def db():
    return open_db(":memory:")

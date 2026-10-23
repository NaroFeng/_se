"""Pytest configuration and shared fixtures."""
import os
import sys
from pathlib import Path

import pytest
from flask import g

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app  # noqa: E402
from config import TestConfig  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "test.sqlite"
    cfg = TestConfig()
    cfg.DATABASE_PATH = str(db_path)
    app = create_app(cfg)
    app.config.update(TESTING=True)
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    from models import get_db
    with app.app_context():
        yield get_db()
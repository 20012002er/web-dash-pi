"""Shared pytest fixtures for the web-dash-pi test suite.

Sets up a temporary config file (copied from ``device_dev.json``), points the
``Config`` class at it via monkeypatching, and exposes a Flask test client
backed by a minimal app that registers the blueprints under test.
"""

import os
import sys
import shutil
import json
from pathlib import Path

import pytest

# Make the ``src`` package importable without requiring an install.
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# ``resolve_path`` (used inside the blueprints) consults SRC_DIR so plugin
# templates / static files resolve against the real src tree during tests.
os.environ.setdefault("SRC_DIR", SRC_DIR)

from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from refresh_task import RefreshTask  # noqa: E402
from blueprints.main import main_bp  # noqa: E402
from blueprints.plugin import plugin_bp  # noqa: E402


@pytest.fixture
def temp_config_file(tmp_path):
    """Copy ``device_dev.json`` to a temp directory and return the new path."""
    src = os.path.join(Config.BASE_DIR, "config", "device_dev.json")
    dst = tmp_path / "device_test.json"
    shutil.copyfile(src, dst)
    return str(dst)


@pytest.fixture
def config(temp_config_file, monkeypatch):
    """Return a ``Config`` instance pointing at the temp config file."""
    monkeypatch.setattr(Config, "config_file", temp_config_file)
    return Config()


@pytest.fixture
def app(config):
    """Build a minimal Flask app with the main + plugin blueprints registered."""
    flask_app = Flask(
        __name__,
        static_folder=os.path.join(SRC_DIR, "static"),
        template_folder=os.path.join(SRC_DIR, "templates"),
    )
    flask_app.config["DEVICE_CONFIG"] = config
    flask_app.config["REFRESH_TASK"] = RefreshTask(config)
    flask_app.register_blueprint(main_bp)
    flask_app.register_blueprint(plugin_bp)
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()

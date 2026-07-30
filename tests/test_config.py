"""Tests for the ``Config`` class (JSON-backed device settings)."""

import json
import os

from config import Config


HARDWARE_KEYS = [
    "display_type",
    "resolution",
    "orientation",
    "inverted_image",
    "brightness_schedule",
    "display_transitions",
]


def test_read_config(config):
    """Config loads successfully and has expected keys."""
    cfg = config.get_config()
    assert isinstance(cfg, dict)
    for key in ("name", "timezone", "loop_enabled"):
        assert key in cfg, f"missing expected key: {key}"


def test_config_has_no_hardware_keys(config):
    """Web dashboard config should not carry display/hardware attributes."""
    cfg = config.get_config()
    for key in HARDWARE_KEYS:
        assert key not in cfg, f"hardware key '{key}' should not be present"


def test_write_config_atomic(config, temp_config_file):
    """write_config persists changes atomically and re-reads cleanly."""
    original = config.get_config("name")
    new_name = "TestDevice-Rewritten"
    assert original != new_name

    config.update_value("name", new_name)
    config.write_config()

    with open(temp_config_file) as f:
        persisted = json.load(f)
    assert persisted["name"] == new_name

    # Re-read via a fresh Config to confirm persistence on disk
    reloaded = Config()
    reloaded.config_file = temp_config_file
    reloaded.config = reloaded.read_config()
    assert reloaded.get_config("name") == new_name


def test_get_plugins(config):
    """get_plugins returns a list of plugin config dicts."""
    plugins = config.get_plugins()
    assert isinstance(plugins, list)
    # Each entry should at least be a dict (may be empty if plugins dir absent).
    for plugin in plugins:
        assert isinstance(plugin, dict)


def test_loop_override(config):
    """set_loop_override persists an override and clear_loop_override removes it."""
    assert config.get_loop_override() is None

    override = {"type": "plugin", "plugin_id": "clock"}
    config.set_loop_override(override)
    assert config.get_loop_override() == override

    config.clear_loop_override()
    assert config.get_loop_override() is None

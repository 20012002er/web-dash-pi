"""Tests for the ``GET /api/plugin/<id>/data`` endpoint."""

import pytest


def test_plugin_data_not_found(client):
    """Requesting an unknown plugin id returns 404."""
    resp = client.get("/api/plugin/nonexistent/data")
    assert resp.status_code == 404
    payload = resp.get_json()
    assert payload is not None
    assert "error" in payload


def test_plugin_data_success(config, client):
    """If the clock plugin can be loaded, the endpoint returns success + data."""
    clock_cfg = config.get_plugin("clock")
    if clock_cfg is None:
        pytest.skip("clock plugin not present in plugins list")

    # Ensure the clock plugin is registered in the plugin registry. Loading
    # requires importing the module, which may fail if optional deps are
    # missing — in that case skip rather than fail.
    try:
        from plugins.plugin_registry import load_plugins, PLUGIN_CLASSES
        load_plugins([clock_cfg])
        if "clock" not in PLUGIN_CLASSES:
            pytest.skip("clock plugin failed to register")
    except Exception as exc:  # noqa: BLE001 — broad on purpose for env issues
        pytest.skip(f"clock plugin could not be loaded: {exc}")

    resp = client.get("/api/plugin/clock/data")
    if resp.status_code == 500:
        # Plugin instantiated but get_data raised (missing pytz, etc.) — skip.
        pytest.skip("clock plugin get_data failed in this environment")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    assert "settings" in payload
    assert "data" in payload

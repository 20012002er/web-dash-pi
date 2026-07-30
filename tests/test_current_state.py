"""Tests for the ``GET /api/current_state`` endpoint."""

REQUIRED_KEYS = {
    "plugin_id",
    "loop_name",
    "remaining_seconds",
    "next_plugin_id",
    "override",
    "loop_enabled",
    "current_plugin",
    "next_plugin",
}


def test_current_state_returns_json(client):
    """Endpoint responds with 200 and JSON."""
    resp = client.get("/api/current_state")
    assert resp.status_code == 200
    assert resp.is_json
    assert isinstance(resp.get_json(), dict)


def test_current_state_has_required_keys(client):
    """Response payload contains every documented state key."""
    payload = client.get("/api/current_state").get_json()
    missing = REQUIRED_KEYS - set(payload.keys())
    assert not missing, f"missing keys: {missing}"


def test_current_state_no_loop(config, client):
    """With no loops configured, plugin_id should be None."""
    # Make sure the loop manager has no loops
    lm = config.get_loop_manager()
    lm.loops = []
    config.update_value("loop_enabled", True)

    payload = client.get("/api/current_state").get_json()
    assert payload["plugin_id"] is None
    assert payload["loop_name"] is None

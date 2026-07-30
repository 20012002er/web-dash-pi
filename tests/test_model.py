"""Tests for the data models (RefreshInfo, LoopManager, Loop, PluginReference)."""

from datetime import datetime

from model import RefreshInfo, LoopManager, Loop, PluginReference


# --------------------------------------------------------------------------- #
# RefreshInfo
# --------------------------------------------------------------------------- #
def test_refresh_info_no_image_hash():
    """RefreshInfo.to_dict() must not carry an ``image_hash`` key (web dashboard)."""
    info = RefreshInfo(
        refresh_type="Manual Update",
        plugin_id="clock",
        refresh_time=datetime.now().isoformat(),
        loop="day",
    )
    payload = info.to_dict()
    assert "image_hash" not in payload
    # Sanity-check the keys that should be present
    assert payload["plugin_id"] == "clock"
    assert payload["refresh_type"] == "Manual Update"


# --------------------------------------------------------------------------- #
# LoopManager / Loop
# --------------------------------------------------------------------------- #
def test_loop_manager_create_loop():
    """Adding a loop makes it retrievable by name."""
    lm = LoopManager()
    assert lm.get_loop("day") is None
    assert lm.add_loop("day", "08:00", "20:00") is True
    loop = lm.get_loop("day")
    assert loop is not None
    assert loop.name == "day"
    assert loop.start_time == "08:00"
    assert loop.end_time == "20:00"
    # Duplicate add should fail
    assert lm.add_loop("day", "08:00", "20:00") is False


def test_loop_scheduling():
    """determine_active_loop picks the loop active at a given time.

    Loops are only considered active when they have plugins in their
    ``plugin_order`` (see LoopManager.determine_active_loop), so we add a
    plugin to each loop before asserting.
    """
    lm = LoopManager()
    lm.add_loop("day", "08:00", "20:00")
    lm.add_loop("night", "20:00", "08:00")
    # determine_active_loop ignores loops without plugins
    lm.get_loop("day").add_plugin("clock", 60)
    lm.get_loop("night").add_plugin("weather", 60)

    noon = datetime(2024, 1, 1, 12, 0)
    active = lm.determine_active_loop(noon)
    assert active is not None
    assert active.name == "day"

    late = datetime(2024, 1, 1, 22, 0)
    active_late = lm.determine_active_loop(late)
    assert active_late is not None
    assert active_late.name == "night"


def test_loop_wrap_midnight():
    """A loop whose end_time < start_time wraps past midnight."""
    loop = Loop("night", "22:00", "06:00")
    # Inside the window — before midnight
    assert loop.is_active("23:30") is True
    # Inside the window — after midnight
    assert loop.is_active("02:15") is True
    # Outside the window
    assert loop.is_active("12:00") is False
    assert loop.is_active("21:59") is False


def test_loop_randomize():
    """In randomize mode, get_next_plugin returns a plugin from the rotation."""
    loop = Loop("rand", "00:00", "23:59", randomize=True)
    loop.add_plugin("clock", 60)
    loop.add_plugin("weather", 60)
    loop.add_plugin("stocks", 60)

    ref = loop.get_next_plugin()
    assert ref is not None
    assert ref.plugin_id in {"clock", "weather", "stocks"}


def test_loop_priority():
    """Smaller time-range loops have higher priority (sort first)."""
    narrow = Loop("narrow", "10:00", "11:00")   # 60 min
    wide = Loop("wide", "06:00", "20:00")        # 14h

    assert narrow.get_priority() < wide.get_priority()
    assert narrow.get_priority() == 60

    lm = LoopManager()
    lm.loops = [wide, narrow]
    # Both need at least one plugin for determine_active_loop to consider them
    narrow.add_plugin("a", 60)
    wide.add_plugin("b", 60)

    active = lm.determine_active_loop(datetime(2024, 1, 1, 10, 30))
    assert active is not None
    assert active.name == "narrow"


# --------------------------------------------------------------------------- #
# PluginReference
# --------------------------------------------------------------------------- #
def test_plugin_reference_should_refresh():
    """should_refresh is True when no prior refresh, False within the interval."""
    ref = PluginReference(plugin_id="clock", refresh_interval_seconds=60)

    # Never refreshed -> needs refresh
    now = datetime(2024, 1, 1, 12, 0, 0)
    assert ref.should_refresh(now) is True

    # Just refreshed -> no refresh needed
    ref.latest_refresh_time = "2024-01-01T12:00:00"
    assert ref.should_refresh(datetime(2024, 1, 1, 12, 0, 30)) is False

    # Past the interval -> refresh needed
    assert ref.should_refresh(datetime(2024, 1, 1, 12, 1, 1)) is True

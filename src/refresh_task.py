"""Refresh task — stateless service for the web dashboard.

Ported from the original OpenClaw-DashPi project, but transformed from a
background thread that renders images into a stateless service that the
blueprints call. Instead of pushing images to a display, blueprints query
``RefreshTask.get_current_state()`` (which reads config live) and call
``record_refresh()`` after a plugin's ``get_data()`` has been invoked.

Action marker classes (ManualRefresh, LoopRefresh, AutoRefresh) are retained
in a simplified form so calling code can pass typed actions to
``manual_update`` / ``queue_manual_update``.
"""

import logging
from datetime import datetime

from model import RefreshInfo

logger = logging.getLogger(__name__)


class RefreshAction:
    """Base marker class for refresh actions.

    Simplified: stores a plugin_id plus optional settings, loop name, and
    plugin reference. Subclasses are typed markers (ManualRefresh,
    LoopRefresh, AutoRefresh) — they no longer execute image generation.
    """

    def __init__(self, plugin_id, settings=None, loop=None, plugin_reference=None):
        self.plugin_id = plugin_id
        self.settings = settings or {}
        self.loop = loop
        self.plugin_reference = plugin_reference

    def get_plugin_id(self):
        return self.plugin_id


class ManualRefresh(RefreshAction):
    """Marker for a user-initiated manual refresh of a plugin."""

    def __init__(self, plugin_id, settings=None, loop=None, plugin_reference=None):
        super().__init__(plugin_id, settings=settings, loop=loop, plugin_reference=plugin_reference)


class LoopRefresh(RefreshAction):
    """Marker for an automatic loop-rotation refresh."""

    def __init__(self, plugin_id, settings=None, loop=None, plugin_reference=None):
        super().__init__(plugin_id, settings=settings, loop=loop, plugin_reference=plugin_reference)


class AutoRefresh(RefreshAction):
    """Marker for an auto-refresh of the currently displayed plugin."""

    def __init__(self, plugin_id, settings=None, loop=None, plugin_reference=None):
        super().__init__(plugin_id, settings=settings, loop=loop, plugin_reference=plugin_reference)


class RefreshTask:
    """Stateless service exposing the current dashboard state to blueprints.

    Unlike the original background-thread RefreshTask, this class does not
    render images or push anything to a display. Instead:
      * ``get_current_state()`` consults the live config (loop override,
        loop_enabled, LoopManager) to decide which plugin should be active
        now, and also drives loop rotation when the interval has elapsed.
      * ``record_refresh()`` persists a RefreshInfo entry.
    """

    def __init__(self, config):
        self.config = config
        self.running = True
        self.last_loop_rotation_time = datetime.now()

    # ------------------------------------------------------------------
    # Refresh recording
    # ------------------------------------------------------------------
    def record_refresh(self, plugin_id, refresh_type, loop_name=None):
        """Persist a RefreshInfo entry after a plugin's data has been refreshed.

        In the web dashboard, refreshes are infrequent (triggered by manual
        updates or loop rotations every few minutes), so we write to disk on
        every call. This guarantees loop state survives server restarts.
        """
        self.config.refresh_info = RefreshInfo(
            refresh_type=refresh_type,
            plugin_id=plugin_id,
            refresh_time=datetime.now().isoformat(),
            loop=loop_name,
        )
        self.config.write_config()

    def signal_config_change(self):
        """Notify that config has changed.

        No-op equivalent: the next ``get_current_state`` call naturally
        re-reads the live config, so there is nothing to invalidate. Kept
        for API parity with the original RefreshTask.
        """
        # Intentionally a no-op — config is read live by get_current_state().
        return None

    def reset_rotation_timer(self):
        """Reset the loop rotation timer to now.

        Call this after a manual skip so the next automatic rotation
        waits a full interval instead of firing immediately.
        """
        self.last_loop_rotation_time = datetime.now()

    # ------------------------------------------------------------------
    # Manual update entry points (kept for API parity)
    # ------------------------------------------------------------------
    def queue_manual_update(self, action):
        """Record a manual update for the given action. Returns True.

        Sync equivalent of ``manual_update`` — in the web dashboard there is
        no background thread to wake, so both paths simply persist the
        refresh record.
        """
        loop_name = getattr(action, "loop", None)
        self.record_refresh(action.plugin_id, "Manual Update", loop_name=loop_name)
        return True

    def manual_update(self, action):
        """Synchronous manual update (alias of queue_manual_update)."""
        return self.queue_manual_update(action)

    # ------------------------------------------------------------------
    # State snapshot for the frontend
    # ------------------------------------------------------------------
    def get_current_state(self):
        """Return a dict snapshot describing the current dashboard state.

        This method also drives the loop rotation: when the rotation
        interval has elapsed since the last rotation, the active loop's
        plugin index is advanced and the new state is persisted.

        Keys:
            plugin_id:           active plugin id (or None)
            loop_name:           active loop name (or None)
            remaining_seconds:   seconds until next loop rotation
            next_plugin_id:      peek of the next plugin in the active loop
            override:            current loop_override dict (or None)
            loop_enabled:        whether looping is enabled
            current_plugin:      display name of the active plugin
            next_plugin:         display name of the next plugin
        """
        loop_manager = self.config.get_loop_manager()
        loop_override = self.config.get_loop_override()
        loop_enabled = self.config.get_config("loop_enabled", default=True)

        # --- Resolve override (plugin pin) ---
        if loop_override and loop_override.get("type") == "plugin":
            plugin_id = loop_override.get("plugin_id")
            return self._build_state(
                plugin_id, None, loop_manager, loop_override, loop_enabled,
            )

        # --- Loop disabled ---
        if not loop_enabled or loop_manager is None:
            return self._build_state(
                None, None, loop_manager, loop_override, loop_enabled,
            )

        # --- Determine active loop ---
        loop = loop_manager.determine_active_loop(
            datetime.now(), override=loop_override,
        )
        if loop is None or not loop.plugin_order:
            return self._build_state(
                None, None, loop_manager, loop_override, loop_enabled,
            )

        # --- Auto-rotate when the rotation interval has elapsed ---
        rotation_interval = loop_manager.rotation_interval_seconds
        now = datetime.now()

        if rotation_interval and self.last_loop_rotation_time:
            elapsed = (now - self.last_loop_rotation_time).total_seconds()
            if elapsed >= rotation_interval:
                ref = loop.get_next_plugin()
                if ref:
                    self.last_loop_rotation_time = now
                    self.record_refresh(ref.plugin_id, "Loop", loop_name=loop.name)

        # --- Read current plugin (peek, do NOT advance) ---
        # If indices are not yet initialised (e.g. first start after upgrade),
        # call get_next_plugin() once to set them up without rotating away
        # from the intended first plugin.
        if loop.next_plugin_index is None and loop.current_plugin_index is None:
            ref = loop.get_next_plugin()
            if ref:
                self.last_loop_rotation_time = now
                self.record_refresh(ref.plugin_id, "Loop", loop_name=loop.name)
        else:
            # Current plugin is at current_plugin_index, NOT next_plugin_index.
            # peek_next_plugin() returns the NEXT plugin, so we must read
            # the current one directly from plugin_order.
            idx = loop.current_plugin_index
            if idx is not None and 0 <= idx < len(loop.plugin_order):
                ref = loop.plugin_order[idx]
            else:
                ref = loop.peek_next_plugin()
        if ref is None:
            return self._build_state(
                None, None, loop_manager, loop_override, loop_enabled,
            )

        return self._build_state(
            ref.plugin_id, loop.name, loop_manager, loop_override,
            loop_enabled, active_loop=loop,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_state(self, plugin_id, loop_name, loop_manager, loop_override,
                     loop_enabled, active_loop=None):
        """Assemble the state dict returned by ``get_current_state``."""
        rotation_interval = (
            loop_manager.rotation_interval_seconds if loop_manager else 0
        )
        if self.last_loop_rotation_time and rotation_interval:
            elapsed = (datetime.now() - self.last_loop_rotation_time).total_seconds()
            remaining_seconds = max(0, int(rotation_interval - elapsed))
        else:
            remaining_seconds = int(rotation_interval) if rotation_interval else 0

        # Peek the next plugin from the active loop, if any
        next_plugin_id = None
        if loop_manager:
            al = active_loop
            if al is None:
                loop_override_cur = self.config.get_loop_override()
                al = loop_manager.determine_active_loop(
                    datetime.now(), override=loop_override_cur
                ) if loop_name else loop_manager.get_loop(loop_name)
            if al and al.plugin_order:
                next_ref = al.peek_next_plugin()
                if next_ref:
                    next_plugin_id = next_ref.plugin_id

        return {
            "plugin_id": plugin_id,
            "loop_name": loop_name,
            "remaining_seconds": remaining_seconds,
            "next_plugin_id": next_plugin_id,
            "override": loop_override,
            "loop_enabled": loop_enabled,
            "current_plugin": self._get_display_name(plugin_id),
            "next_plugin": self._get_display_name(next_plugin_id),
        }

    def _get_display_name(self, plugin_id):
        """Look up a plugin's human-readable display name in plugins_list."""
        if not plugin_id:
            return None
        cfg = self.config.get_plugin(plugin_id)
        return cfg.get("display_name", plugin_id) if cfg else plugin_id

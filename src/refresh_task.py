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
      * ``determine_current_plugin()`` consults the live config (loop override,
        loop_enabled, LoopManager) to decide which plugin should be active now.
      * ``record_refresh()`` persists a RefreshInfo entry (throttled to reduce
        disk writes, matching the original's 12-call batch cadence).
      * ``get_current_state()`` returns the snapshot the frontend polls.
    """

    # Throttle: only persist to disk every N refresh records
    CONFIG_WRITE_INTERVAL = 12

    def __init__(self, config):
        self.config = config
        self.running = True
        self.last_loop_rotation_time = datetime.now()
        # Counter mirroring the original batched-write cadence
        self._refresh_counter = 0

    # ------------------------------------------------------------------
    # Plugin selection
    # ------------------------------------------------------------------
    def determine_current_plugin(self):
        """Determine which plugin should be active right now.

        Resolution order:
          1. ``loop_override`` of type ``"plugin"`` → return that plugin with
             ``loop_name=None``.
          2. ``loop_override`` of type ``"loop"`` → use that loop's next plugin.
          3. If ``loop_enabled`` is False → return ``(None, None)``.
          4. Otherwise consult ``LoopManager.determine_active_loop`` and return
             the loop's current/next plugin plus the loop name.
          5. Fall back to ``(None, None)`` if nothing is active.

        Returns:
            tuple: ``(plugin_id, loop_name)`` where either may be ``None``.
        """
        loop_override = self.config.get_loop_override()

        if loop_override:
            if loop_override.get("type") == "plugin":
                return loop_override.get("plugin_id"), None
            if loop_override.get("type") == "loop":
                loop_name = loop_override.get("loop_name")
                loop = self.config.get_loop_manager().get_loop(loop_name) if loop_name else None
                if loop and loop.plugin_order:
                    ref = loop.peek_next_plugin() or loop.get_next_plugin()
                    if ref:
                        return ref.plugin_id, loop.name
                # fall through if override loop not found / empty

        loop_enabled = self.config.get_config("loop_enabled", default=True)
        if not loop_enabled:
            return None, None

        loop_manager = self.config.get_loop_manager()
        if loop_manager is None:
            return None, None

        loop = loop_manager.determine_active_loop(datetime.now(), override=loop_override)
        if loop is None or not loop.plugin_order:
            return None, None

        # Prefer the loop's pre-computed current/next plugin so the frontend
        # stays in sync with the LoopManager's state machine.
        ref = loop.peek_next_plugin() or loop.get_next_plugin()
        if ref is None:
            return None, None
        return ref.plugin_id, loop.name

    # ------------------------------------------------------------------
    # Refresh recording
    # ------------------------------------------------------------------
    def record_refresh(self, plugin_id, refresh_type, loop_name=None):
        """Persist a RefreshInfo entry after a plugin's data has been refreshed.

        Mirrors the original's throttled-write behaviour: only every
        ``CONFIG_WRITE_INTERVAL`` calls actually flush to disk, reducing
        wear on the underlying storage.
        """
        self.config.refresh_info = RefreshInfo(
            refresh_type=refresh_type,
            plugin_id=plugin_id,
            refresh_time=datetime.now().isoformat(),
            loop=loop_name,
        )
        self._refresh_counter += 1
        if self._refresh_counter >= self.CONFIG_WRITE_INTERVAL:
            logger.debug(
                "Writing config to disk (batched after %d refreshes)",
                self._refresh_counter,
            )
            self.config.write_config()
            self._refresh_counter = 0

    def signal_config_change(self):
        """Notify that config has changed.

        No-op equivalent: the next ``get_current_state`` call naturally
        re-reads the live config, so there is nothing to invalidate. Kept
        for API parity with the original RefreshTask.
        """
        # Intentionally a no-op — config is read live by get_current_state().
        return None

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
        plugin_id, loop_name = self.determine_current_plugin()

        loop_manager = self.config.get_loop_manager()
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
            loop_override = self.config.get_loop_override()
            active_loop = loop_manager.determine_active_loop(
                datetime.now(), override=loop_override
            ) if loop_name else loop_manager.get_loop(loop_name)
            if active_loop and active_loop.plugin_order:
                next_ref = active_loop.peek_next_plugin()
                if next_ref:
                    next_plugin_id = next_ref.plugin_id

        return {
            "plugin_id": plugin_id,
            "loop_name": loop_name,
            "remaining_seconds": remaining_seconds,
            "next_plugin_id": next_plugin_id,
            "override": self.config.get_loop_override(),
            "loop_enabled": self.config.get_config("loop_enabled", default=True),
            "current_plugin": self._get_display_name(plugin_id),
            "next_plugin": self._get_display_name(next_plugin_id),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_display_name(self, plugin_id):
        """Look up a plugin's human-readable display name in plugins_list."""
        if not plugin_id:
            return None
        cfg = self.config.get_plugin(plugin_id)
        return cfg.get("display_name", plugin_id) if cfg else plugin_id

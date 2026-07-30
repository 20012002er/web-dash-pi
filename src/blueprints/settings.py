"""Settings blueprint — device config (name, timezone, time format, proxy)."""

from flask import Blueprint, request, jsonify, current_app, render_template
import pytz
import logging

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)


@settings_bp.route('/settings')
def settings_page():
    """Render device settings page (timezone, time format, proxy)."""
    device_config = current_app.config['DEVICE_CONFIG']
    timezones = sorted(pytz.all_timezones_set)

    return render_template(
        'settings.html',
        device_settings=device_config.get_config(),
        timezones=timezones,
    )


@settings_bp.route('/update_settings', methods=['POST'])
def update_settings():
    """Save device settings from the settings form.

    Only processes: name, timezone, time_format, and proxy. Display-related
    fields (display_type, resolution, orientation, inverted_image,
    brightness_schedule, display_transitions) are intentionally ignored —
    the web dashboard renders in the browser, not on a physical display.
    """
    device_config = current_app.config['DEVICE_CONFIG']

    try:
        form_data = request.form.to_dict()

        time_format = form_data.get("timeFormat")
        if not form_data.get("timezoneName"):
            return jsonify({"error": "Time Zone is required"}), 400
        if not time_format or time_format not in ["12h", "24h"]:
            return jsonify({"error": "Time format is required"}), 400

        # Device name (optional — fall back to existing if blank)
        device_name = form_data.get("deviceName", "").strip() or None

        proxy_enabled = "proxyEnabled" in form_data
        proxy_host = form_data.get("proxyHost", "").strip()
        proxy_port = form_data.get("proxyPort", "").strip()

        # Read current proxy config so we can detect a change
        current_proxy = device_config.get_config("proxy", default={}) or {}
        proxy_changed = (
            bool(proxy_enabled) != bool(current_proxy.get("enabled"))
            or proxy_host != (current_proxy.get("host") or "")
            or proxy_port != (current_proxy.get("port") or "")
        )

        # Persist each kept field individually
        if device_name is not None:
            device_config.update_value("device_name", device_name)
        device_config.update_value("timezone", form_data.get("timezoneName"))
        device_config.update_value("time_format", time_format)
        device_config.update_value(
            "proxy",
            {
                "enabled": proxy_enabled,
                "host": proxy_host,
                "port": proxy_port,
            },
        )

        # Apply proxy env vars immediately if the proxy config changed
        if proxy_changed:
            device_config._apply_proxy_settings()

        device_config.write_config()

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    return jsonify({"success": True, "message": "Saved settings."})

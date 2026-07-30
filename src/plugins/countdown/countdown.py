"""Countdown plugin — returns days remaining until or passed since a target date.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image, ``get_data`` returns a dict with the title, target date, day count, and
label ("DAYS LEFT" / "DAYS PASSED"), plus the user's background/text colors.
The frontend ``dashboard.html`` fragment lays out the centered vertical display.
"""

import logging
from datetime import datetime

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"


class Countdown(BasePlugin):
    """Renders a day counter showing days remaining until or elapsed since a target date."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Calculate days to/from the target date and return the countdown data."""
        import pytz

        title = settings.get('title')
        countdown_date_str = settings.get('date')

        if not countdown_date_str:
            raise RuntimeError("Date is required.")

        timezone_name = device_config.get_config("timezone", DEFAULT_TIMEZONE)
        try:
            tz = pytz.timezone(timezone_name)
        except Exception as e:
            logger.warning("Invalid timezone '%s', falling back to %s: %s",
                           timezone_name, DEFAULT_TIMEZONE, e)
            tz = pytz.timezone(DEFAULT_TIMEZONE)

        current_time = datetime.now(tz)

        try:
            countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")
        except ValueError:
            raise RuntimeError("Invalid date format. Use YYYY-MM-DD.")

        countdown_date = tz.localize(countdown_date)

        day_count = (countdown_date.date() - current_time.date()).days
        label = "DAYS LEFT" if day_count > 0 else "DAYS PASSED"

        return {
            "title": title or "",
            "target_date": countdown_date.strftime("%B %d, %Y"),
            "target_date_iso": countdown_date_str,
            "days": abs(day_count),
            "label": label,
            "background_color": settings.get("backgroundColor", "#ffffff"),
            "text_color": settings.get("textColor", "#000000"),
        }

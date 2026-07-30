"""Year Progress plugin — returns how much of the current year has elapsed.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image, ``get_data`` returns the year, percent complete, days left, and the
user's background/text colors. The frontend ``dashboard.html`` fragment draws
the progress bar with CSS.
"""

import logging
from datetime import datetime

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"


class YearProgress(BasePlugin):
    """Calculates the current year's progress and returns it for the frontend to render."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Calculate year progress percentage and return the display data."""
        import pytz

        timezone_name = device_config.get_config("timezone", DEFAULT_TIMEZONE)
        try:
            tz = pytz.timezone(timezone_name)
        except Exception as e:
            logger.warning("Invalid timezone '%s', falling back to %s: %s",
                           timezone_name, DEFAULT_TIMEZONE, e)
            tz = pytz.timezone(DEFAULT_TIMEZONE)

        current_time = datetime.now(tz)

        start_of_year = datetime(current_time.year, 1, 1, tzinfo=tz)
        start_of_next_year = datetime(current_time.year + 1, 1, 1, tzinfo=tz)

        total_days = (start_of_next_year - start_of_year).days
        days_left = (start_of_next_year - current_time).total_seconds() / (24 * 3600)
        elapsed_days = (current_time - start_of_year).total_seconds() / (24 * 3600)

        year_percent = round((elapsed_days / total_days) * 100)

        return {
            "year": current_time.year,
            "percent": year_percent,
            "days_left": round(days_left),
            "background_color": settings.get("backgroundColor", "#ffffff"),
            "text_color": settings.get("textColor", "#000000"),
        }

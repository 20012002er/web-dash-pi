"""Clock plugin — returns the current time for one of four clock faces.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image per face, ``get_data`` returns a JSON-serializable dict describing the
current time (HH:MM string, date string, integer hour/minute/second, selected
face name, and the user's primary/secondary colors). The frontend
``dashboard.html`` fragment draws the analog/digital/word/divided faces with
CSS and SVG.
"""

import logging
from datetime import datetime

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

# Available clock face styles. Each entry defines the face name, default colors,
# and a preview icon shown in the settings UI.
CLOCK_FACES = [
    {
        "name": "Gradient Clock",
        "primary_color": "#db3246",
        "secondary_color": "#000000",
        "icon": "faces/gradient.png"
    },
    {
        "name": "Digital Clock",
        "primary_color": "#ffffff",
        "secondary_color": "#000000",
        "icon": "faces/digital.png"
    },
    {
        "name": "Divided Clock",
        "primary_color": "#20b7ae",
        "secondary_color": "#ffffff",
        "icon": "faces/divided.png"
    },
    {
        "name": "Word Clock",
        "primary_color": "#000000",
        "secondary_color": "#ffffff",
        "icon": "faces/word.png"
    }
]

DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CLOCK_FACE = "Gradient Clock"

# Map the settings-page face name to the short id used in the returned data.
FACE_ID_BY_NAME = {
    "Gradient Clock": "gradient",
    "Digital Clock": "digital",
    "Divided Clock": "divided",
    "Word Clock": "word",
}


class Clock(BasePlugin):
    """Analog and digital clock plugin with four face styles.

    Face styles: Gradient (conic gradient with analog hands), Digital (DS-Digital
    font), Divided (two-tone analog), and Word (letter grid that spells out the
    time in English). All faces support user-configurable primary/secondary colors.
    """

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['clock_faces'] = CLOCK_FACES
        return template_params

    def get_data(self, settings, device_config):
        """Return the current time in the selected timezone and face style.

        The frontend ``dashboard.html`` renders the four face styles purely in
        CSS/SVG, so the backend only needs to send the time and colors.
        """
        import pytz

        clock_face = settings.get('selectedClockFace')
        if not clock_face or clock_face not in [face['name'] for face in CLOCK_FACES]:
            clock_face = DEFAULT_CLOCK_FACE

        primary_color = settings.get('primaryColor') or CLOCK_FACES[0]["primary_color"]
        secondary_color = settings.get('secondaryColor') or CLOCK_FACES[0]["secondary_color"]

        timezone_name = device_config.get_config("timezone", DEFAULT_TIMEZONE)
        time_format = device_config.get_config("time_format", "12h")

        try:
            tz = pytz.timezone(timezone_name)
        except Exception as e:
            logger.warning("Invalid timezone '%s', falling back to %s: %s",
                           timezone_name, DEFAULT_TIMEZONE, e)
            tz = pytz.timezone(DEFAULT_TIMEZONE)

        current_time = datetime.now(tz)

        # 12h vs 24h display
        if time_format == "24h":
            time_str = f"{current_time.hour:02d}:{current_time.minute:02d}"
            display_hour = current_time.hour
        else:
            display_hour = current_time.hour % 12 or 12
            time_str = f"{display_hour}:{current_time.minute:02d}"

        date_str = current_time.strftime("%A, %B %-d")

        try:
            return {
                "time": time_str,
                "date": date_str,
                "face": FACE_ID_BY_NAME[clock_face],
                "face_name": clock_face,
                "primary_color": primary_color,
                "secondary_color": secondary_color,
                "time_format": time_format,
                "hour": display_hour,
                "minute": current_time.minute,
                "second": current_time.second,
                # 24h hour for analog hand math
                "hour_24": current_time.hour,
            }
        except Exception as e:
            logger.error("Failed to build clock data: %s", e)
            raise RuntimeError("Failed to display clock.")

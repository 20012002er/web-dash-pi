"""ShazamPi music plugin — EXPERIMENTAL web port.

Ported from the original OpenClaw-DashPi project. The original recorded
audio from a USB microphone via ALSA/arecord, ran TFLite YAMNet to detect
music, then called the Shazam API to identify songs. All of that
microphone/ML/Shazam backend logic has been removed for the web version —
the actual audio capture happens in the frontend ``dashboard.html`` using
the Web Audio API (``getUserMedia``), and the recorded clip is intended to
be POSTed to a backend ``/api/plugin/shazam_pi/identify`` endpoint (not yet
implemented).

For now ``get_data`` simply returns an idle status prompting the user to
click "Start Listening". The ``ml-model/`` and ``resources/`` directories
are copied across so a future backend identification endpoint can load
YAMNet, and the frontend can show the default idle image.
"""

import logging
import os

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


class ShazamPi(BasePlugin):
    """EXPERIMENTAL: frontend-driven song identification via the microphone."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        template_params['hide_refresh_interval'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Return an idle status prompting the user to start listening.

        The actual audio recording and identification happen in the frontend
        via the Web Audio API; the backend ``get_data`` only signals the idle
        state and surfaces a short instruction message. A future backend
        endpoint (``/api/plugin/shazam_pi/identify``) will receive the
        recorded clip and return the identified song.

        Returns:
            dict with keys: status, message, default_image_url.
        """
        return {
            "status": "idle",
            "message": "ShazamPi requires browser microphone access. Click to start listening.",
            "recording_duration": int(settings.get("recordingDuration", 5)),
        }

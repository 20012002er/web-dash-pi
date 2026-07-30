"""GitHub plugin — fetches contribution graphs, sponsor counts, or star history.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image, ``get_data`` delegates to one of three helper modules based on the
``githubType`` setting (``contributions``, ``sponsors``, or ``stars``) and
returns a JSON-serializable data dict. The frontend ``dashboard.html``
fragment renders the appropriate visualization (heatmap, sponsor grid, or
star chart) from the returned data. The GitHub GraphQL/REST API logic is
preserved in the helper modules.
"""

import logging

from plugins.base_plugin.base_plugin import BasePlugin
from .github_contributions import get_data as get_contributions_data
from .github_sponsors import get_data as get_sponsors_data
from .github_stars import get_data as get_stars_data

logger = logging.getLogger(__name__)


class GitHub(BasePlugin):
    """Fetches GitHub contribution, sponsor, or star data via the GitHub API."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "GitHub",
            "expected_key": "GITHUB_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Delegate to the appropriate GitHub helper based on the configured type.

        Returns the data dict produced by the selected helper, which is then
        serialized and handed to the frontend ``dashboard.html`` fragment.
        """
        try:
            github_type = settings.get('githubType', 'contributions')

            if github_type == 'contributions':
                return get_contributions_data(self, settings, device_config)
            elif github_type == 'sponsors':
                return get_sponsors_data(self, settings, device_config)
            elif github_type == 'stars':
                return get_stars_data(self, settings, device_config)
            else:
                logger.error("Unknown GitHub type: %s", github_type)
                raise ValueError(f"Unknown GitHub type: {github_type}")
        except Exception as e:
            logger.error("GitHub data fetch failed: %s", str(e))
            raise

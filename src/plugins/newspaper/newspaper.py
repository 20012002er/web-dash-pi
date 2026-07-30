"""Newspaper plugin — returns today's newspaper front page image URL.

Ported from the original OpenClaw-DashPi project. Instead of downloading and
fitting a PIL image, ``get_data`` returns the image URL (and the newspaper's
display name as the title) so the frontend ``dashboard.html`` fragment can
render the front page via an ``<img>`` tag. The Freedom Forum URL pattern is
probed across a small window of days (tomorrow down to two days ago) and the
first responding image is returned.
"""

import logging
from datetime import datetime, timedelta

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.newspaper.constants import NEWSPAPERS

logger = logging.getLogger(__name__)

FREEDOM_FORUM_URL = "https://cdn.freedomforum.org/dfp/jpg{}/lg/{}.jpg"


class Newspaper(BasePlugin):
    """Fetches and displays a newspaper front page image from the Freedom Forum archive."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['newspapers'] = sorted(NEWSPAPERS, key=lambda n: n['name'])
        return template_params

    def get_data(self, settings, device_config):
        """Locate the latest available front page URL for the selected newspaper."""
        from utils.http_client import get_http_session

        newspaper_slug = settings.get('newspaperSlug')
        newspaper_name = settings.get('newspaperName') or ""

        if not newspaper_slug:
            raise RuntimeError("Newspaper input not provided.")
        newspaper_slug = newspaper_slug.upper()

        today = datetime.today()

        # Check the next day, then today, then prior days.
        days = [today + timedelta(days=diff) for diff in [1, 0, -1, -2]]

        session = get_http_session()
        for date in days:
            image_url = FREEDOM_FORUM_URL.format(date.day, newspaper_slug)
            try:
                resp = session.head(image_url, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    logger.info("Found %s front cover for %s",
                                newspaper_slug, date.strftime('%Y-%m-%d'))
                    return {
                        "image_url": image_url,
                        "title": newspaper_name or newspaper_slug,
                    }
            except Exception as e:
                logger.debug("Failed to check newspaper for %s: %s",
                             date.strftime('%Y-%m-%d'), e)
                continue

        raise RuntimeError("Newspaper front cover not found.")

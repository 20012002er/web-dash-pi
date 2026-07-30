"""APOD plugin — fetches NASA's Astronomy Picture of the Day.

Ported from the original OpenClaw-DashPi project. The original implementation
downloaded the APOD image via the adaptive image loader, added a title overlay
with PIL, and returned a rendered image. This web version keeps all of the
NASA API logic (date modes for today/custom/random, retry loop to skip video
entries) and returns the direct image URL plus metadata for the frontend
``dashboard.html`` fragment to render. The PIL title overlay and the
``image_loader`` have been removed accordingly.
"""

import logging
import re
from datetime import datetime, timedelta
from random import randint

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

API_TIMEOUT = 15  # Seconds before giving up on NASA API metadata request

logger = logging.getLogger(__name__)


class Apod(BasePlugin):
    """Fetches NASA's Astronomy Picture of the Day and returns its URL + metadata."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "NASA",
            "expected_key": "NASA_SECRET"
        }
        template_params['style_settings'] = False
        return template_params

    def get_data(self, settings, device_config):
        """Fetch the APOD image URL and metadata for the configured or random date.

        Args:
            settings: Plugin settings dict containing ``randomizeApod`` and
                ``customDate``.
            device_config: Device configuration object, used to load the
                ``NASA_SECRET`` environment variable.

        Returns:
            dict: ``{image_url: str, title: str, explanation: str, date: str}``
            for the frontend.
        """
        logger.info("=== APOD Plugin: Starting data fetch ===")

        api_key = device_config.load_env_key("NASA_SECRET")
        if not api_key:
            logger.error("NASA API Key not configured")
            raise RuntimeError("NASA API Key not configured.")

        # Retry up to 10 times to find an image (not video)
        max_retries = 10
        is_random = settings.get("randomizeApod") == "true"
        custom_date = settings.get("customDate")

        data = None
        for attempt in range(max_retries):
            params = {"api_key": api_key}

            # Determine date to fetch
            if is_random:
                start = datetime(2015, 1, 1)
                end = datetime.today()
                delta_days = (end - start).days
                random_date = start + timedelta(days=randint(0, delta_days))
                params["date"] = random_date.strftime("%Y-%m-%d")
                logger.info(f"Fetching random APOD from date: {params['date']} (attempt {attempt + 1})")
            elif custom_date:
                # If custom date specified, go back day by day on retries
                target_date = datetime.strptime(custom_date, "%Y-%m-%d") - timedelta(days=attempt)
                params["date"] = target_date.strftime("%Y-%m-%d")
                logger.info(f"Fetching APOD from date: {params['date']} (attempt {attempt + 1})")
            else:
                # Fetching today's APOD, go back day by day on retries
                target_date = datetime.today() - timedelta(days=attempt)
                params["date"] = target_date.strftime("%Y-%m-%d")
                logger.info(f"Fetching APOD from date: {params['date']} (attempt {attempt + 1})")

            logger.debug("Requesting NASA APOD API...")
            session = get_http_session()
            response = session.get("https://api.nasa.gov/planetary/apod", params=params, timeout=API_TIMEOUT)

            if response.status_code != 200:
                logger.error(f"NASA API error (status {response.status_code}): {response.text}")
                continue  # Try next date

            data = response.json()
            logger.debug(f"APOD API response received: {data.get('title', 'No title')}")

            # Check if it's an image
            if data.get("media_type") == "image":
                logger.info(f"Found APOD image on date: {params['date']}")
                break  # Success! Exit retry loop
            else:
                logger.warning(f"APOD on {params['date']} is a '{data.get('media_type')}', not an image. Trying another date...")
        else:
            # All retries exhausted
            logger.error(f"Failed to find an APOD image after {max_retries} attempts")
            raise RuntimeError(f"Could not find an APOD image after {max_retries} attempts.")

        # Prefer standard URL (typically ~1024px) over HD URL (often 4000px+).
        # The web frontend can handle either, but the standard URL is smaller
        # and faster to transfer.
        image_url = data.get("url") or data.get("hdurl")
        logger.info(f"APOD image URL: {image_url}")

        if not image_url:
            raise RuntimeError("APOD response did not include an image URL.")

        # Clean up the title (strip any HTML entities/tags that occasionally appear)
        title = data.get("title", "")
        if title:
            title = re.sub('<[^<]+?>', '', title)
            title = re.sub(r'&[a-zA-Z]+;', '', title)
            title = ' '.join(title.split()).strip()
            if len(title) > 80:
                title = title[:77] + "..."

        explanation = data.get("explanation", "")
        apod_date = data.get("date", "")

        logger.info("=== APOD Plugin: Data fetch complete ===")
        return {
            "image_url": image_url,
            "title": title,
            "explanation": explanation,
            "date": apod_date,
        }

"""Wikipedia Picture of the Day plugin.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched Wikipedia's POTD via a two-step MediaWiki API call (page → image
info), optionally resized the downloaded image with the adaptive image
loader, and drew a title overlay with PIL. This web version keeps the
two-step API logic, date-mode selection (today / custom / random), and
retry logic intact, but returns the image URL plus title and description as
a dict so the frontend ``dashboard.html`` fragment can render the image with
an HTML overlay.

Wikipedia API documentation:
    https://www.mediawiki.org/wiki/API:Main_page
    https://www.mediawiki.org/wiki/API:Picture_of_the_day_viewer

Flow:
    1. Determine the date to use (today / custom / random).
    2. Query the POTD template page to get the image filename.
    3. Query imageinfo to get the direct image URL + extmetadata (title).
    4. Return the URL + metadata for the frontend to display.

``get_data`` returns:
    {image_url: str, title: str, description: str, date: str}
"""

import logging
import re
from datetime import datetime, timedelta, date
from html import unescape
from random import randint

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)


class Wpotd(BasePlugin):
    """Fetches Wikipedia's Picture of the Day and returns its URL and metadata."""

    HEADERS = {'User-Agent': 'DashPi/2.0'}
    API_URL = "https://en.wikipedia.org/w/api.php"

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        return template_params

    def get_data(self, settings, device_config):
        """Fetch the Wikipedia POTD for the configured date and return its metadata."""
        logger.info("=== Wikipedia POTD Plugin: Starting data fetch ===")

        is_random_mode = settings.get("randomizeWpotd") == "true"
        fit_mode = settings.get("fitMode", "fit")  # Default to 'fit' for letterbox

        # Retry logic for random mode - try up to 5 different dates if one fails
        max_attempts = 5 if is_random_mode else 1
        last_error = None
        datetofetch = None

        for attempt in range(max_attempts):
            try:
                datetofetch = self._determine_date(settings)
                logger.info(
                    "Fetching Wikipedia Picture of the Day for: %s%s",
                    datetofetch,
                    " (attempt {}/{})".format(attempt + 1, max_attempts) if max_attempts > 1 else "",
                )

                data = self._fetch_potd(datetofetch)
                picurl = data["image_src"]
                title = data.get("title", "")
                logger.info("Image URL: %s", picurl)

                logger.info("=== Wikipedia POTD Plugin: Data fetch complete ===")
                if fit_mode not in ("fit", "fill"):
                    fit_mode = "fit"
                return {
                    "image_url": picurl,
                    "title": title,
                    "description": title,  # POTD extmetadata title serves as the caption
                    "date": datetofetch.isoformat(),
                    "fit_mode": fit_mode,
                }

            except Exception as e:
                last_error = e
                if is_random_mode and attempt < max_attempts - 1:
                    logger.warning(
                        "Failed to load WPOTD for %s: %s. Trying another random date...",
                        datetofetch or 'unknown date', e,
                    )
                    continue
                else:
                    break

        logger.error("Failed to download WPOTD image after %d attempt(s)", max_attempts)
        raise RuntimeError(f"Failed to download WPOTD image: {last_error}")

    def _determine_date(self, settings):
        """Determine which date's POTD to fetch based on settings."""
        if settings.get("randomizeWpotd") == "true":
            start = datetime(2015, 1, 1)
            delta_days = (datetime.today() - start).days
            return (start + timedelta(days=randint(0, delta_days))).date()
        elif settings.get("customDate"):
            return datetime.strptime(settings["customDate"], "%Y-%m-%d").date()
        else:
            return datetime.today().date()

    def _fetch_potd(self, cur_date):
        """Two-step fetch: get the POTD image filename, then its imageinfo."""
        title = f"Template:POTD/{cur_date.isoformat()}"
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "images",
            "titles": title,
        }

        data = self._make_request(params)
        try:
            filename = data["query"]["pages"][0]["images"][0]["title"]
        except (KeyError, IndexError) as e:
            logger.error("Failed to retrieve POTD filename for %s: %s", cur_date, e)
            raise RuntimeError("Failed to retrieve POTD filename.")

        image_data = self._fetch_image_src(filename)

        return {
            "filename": filename,
            "image_src": image_data["url"],
            "title": image_data.get("title", ""),
            "image_page_url": f"https://en.wikipedia.org/wiki/{title}",
            "date": cur_date,
        }

    def _fetch_image_src(self, filename):
        """Fetch the direct image URL and a cleaned-up title from extmetadata."""
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "titles": filename,
        }
        data = self._make_request(params)
        try:
            page = next(iter(data["query"]["pages"].values()))
            imageinfo = page["imageinfo"][0]
            url = imageinfo["url"]

            # Try to get a readable title/description from metadata
            title = ""
            extmetadata = imageinfo.get("extmetadata", {})

            # Try ObjectName first (usually the title), then ImageDescription
            if "ObjectName" in extmetadata:
                title = extmetadata["ObjectName"].get("value", "")
            elif "ImageDescription" in extmetadata:
                title = extmetadata["ImageDescription"].get("value", "")

            # Remove all HTML tags and clean up
            if title:
                # Remove HTML tags
                title = re.sub('<[^<]+?>', '', title)
                # Decode HTML entities
                title = unescape(title)
                # Remove any remaining wikitext/labels (like "label QS:Len")
                title = re.sub(r'label\s+QS:[^"]*"([^"]*)".*', r'\1', title)
                # Remove extra quotes and whitespace
                title = title.replace('"', '').strip()
                title = ' '.join(title.split()).strip()

            # Truncate if too long
            if len(title) > 120:
                title = title[:117] + "..."

            return {"url": url, "title": title}
        except (KeyError, IndexError, StopIteration) as e:
            logger.error("Failed to retrieve image info for %s: %s", filename, e)
            raise RuntimeError("Failed to retrieve image info.")

    def _make_request(self, params):
        """Make a MediaWiki API GET request, returning the parsed JSON."""
        try:
            session = get_http_session()
            response = session.get(self.API_URL, params=params, headers=self.HEADERS, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("Wikipedia API request failed with params %s: %s", params, e)
            raise RuntimeError("Wikipedia API request failed.")

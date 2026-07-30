"""Unsplash plugin — fetches a random photo from the Unsplash API.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched a random photo URL from the Unsplash API, downloaded it via the
adaptive image loader, and rendered a PIL image with an optional credit
overlay drawn via PIL. The web version fetches the same metadata and passes
the direct image URL plus the photographer name through to the frontend, which
renders the image with CSS ``object-fit`` and overlays the credit. The
``generate_settings_template()`` override is retained so the API key
requirement (``UNSPLASH_ACCESS_KEY``) is declared.
"""

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session
import logging
import random

logger = logging.getLogger(__name__)


class Unsplash(BasePlugin):
    """Fetches a random Unsplash photo URL and metadata for the frontend to render."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "Unsplash",
            "expected_key": "UNSPLASH_ACCESS_KEY"
        }
        return template_params

    def get_data(self, settings, device_config):
        """Fetch a random Unsplash photo URL matching the configured filters.

        Args:
            settings: Plugin settings dict containing ``search_query``,
                ``collections``, ``content_filter``, ``color``, ``orientation``,
                ``fitMode``, and ``showPhotoInfo``.
            device_config: Device configuration object, used to load the
                ``UNSPLASH_ACCESS_KEY`` environment variable.

        Returns:
            dict: ``{image_url: str, photographer: str, description: str,
            fit_mode: str}`` for the frontend.
        """
        logger.info("=== Unsplash Plugin: Starting data fetch ===")

        access_key = device_config.load_env_key("UNSPLASH_ACCESS_KEY")
        if not access_key:
            logger.error("Unsplash Access Key not found in environment")
            raise RuntimeError("'Unsplash Access Key' not found.")

        search_query = settings.get('search_query')
        collections = settings.get('collections')
        content_filter = settings.get('content_filter', 'low')
        color = settings.get('color')
        orientation = settings.get('orientation')

        # The web frontend handles arbitrary image sizes, so request 'regular'
        # (a reasonable balance of quality vs. payload) instead of 'full'.
        image_size = 'regular'
        logger.info(f"Settings: image_size='{image_size}', content_filter='{content_filter}'")
        if search_query:
            logger.info(f"Search query: '{search_query}'")
        if collections:
            logger.info(f"Collections: {collections}")
        if color:
            logger.debug(f"Color filter: {color}")
        if orientation:
            logger.debug(f"Orientation: {orientation}")

        params = {
            'client_id': access_key,
            'content_filter': content_filter,
            'per_page': 100,
        }

        if search_query:
            url = "https://api.unsplash.com/search/photos"
            params['query'] = search_query
            logger.debug(f"Using search endpoint: {url}")
        else:
            url = "https://api.unsplash.com/photos/random"
            logger.debug(f"Using random photo endpoint: {url}")

        if collections:
            params['collections'] = collections
        if color:
            params['color'] = color
        if orientation:
            params['orientation'] = orientation

        try:
            logger.debug("Fetching image from Unsplash API...")
            session = get_http_session()
            response = session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            if search_query:
                results = data.get("results")
                if not results:
                    logger.warning(f"No images found for search query: '{search_query}'")
                    raise RuntimeError("No images found for the given search query.")
                logger.info(f"Found {len(results)} images matching search query")
                selected_photo = random.choice(results)
                image_url = selected_photo["urls"].get(image_size) or selected_photo["urls"].get("regular")
                photo_data = selected_photo
                logger.debug(f"Selected random image from {len(results)} results")
            else:
                image_url = data["urls"].get(image_size) or data["urls"].get("regular")
                photo_data = data
                logger.debug("Retrieved random image URL")

            if not image_url:
                raise RuntimeError("No image URL found in Unsplash API response.")

            # Extract photo metadata
            description = photo_data.get("description") or photo_data.get("alt_description") or ""
            photographer = ""
            user_data = photo_data.get("user")
            if user_data:
                photographer = user_data.get("name", "")

        except (KeyError, IndexError) as e:
            logger.error(f"Error parsing Unsplash API response: {e}")
            raise RuntimeError("Failed to parse Unsplash API response, please check logs.")
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Error fetching image from Unsplash API: {e}")
            raise RuntimeError("Failed to fetch image from Unsplash API, please check logs.")

        # Get fit mode setting (default to 'fit' for letterbox)
        fit_mode = settings.get("fitMode", "fit")
        if fit_mode not in ("fit", "fill"):
            fit_mode = "fit"
        logger.debug(f"Fit mode: {fit_mode}")

        # Whether to show the photo info overlay on the frontend
        show_photo_info = settings.get("showPhotoInfo") == "true"

        logger.info("=== Unsplash Plugin: Data fetch complete ===")
        return {
            "image_url": image_url,
            "photographer": photographer,
            "description": description,
            "show_photo_info": show_photo_info,
            "fit_mode": fit_mode,
        }

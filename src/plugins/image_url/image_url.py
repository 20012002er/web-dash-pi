"""Image URL plugin — passes through a user-provided image URL for the frontend to render.

Ported from the original OpenClaw-DashPi project. The original implementation
downloaded the image server-side via the adaptive image loader and rendered a
PIL image. The web version simply passes the URL (and fit mode) through to the
frontend ``<img>`` tag, letting the browser handle fetching and display.
"""

from plugins.base_plugin.base_plugin import BasePlugin
import logging

logger = logging.getLogger(__name__)


class ImageURL(BasePlugin):
    """Returns a URL and fit mode for the frontend to render directly."""

    def get_data(self, settings, device_config):
        """Return the configured image URL and fit mode.

        Args:
            settings: Plugin settings dict containing ``url`` and ``fitMode``.
            device_config: Device configuration object (unused for this plugin).

        Returns:
            dict: ``{url: str, fit_mode: "fit"|"fill"}`` for the frontend.
        """
        logger.info("=== Image URL Plugin: Starting data fetch ===")

        url = settings.get('url')
        if not url:
            logger.error("No URL provided in settings")
            raise RuntimeError("URL is required.")

        # Get fit mode setting (default to 'fit' for letterbox)
        fit_mode = settings.get("fitMode", "fit")
        if fit_mode not in ("fit", "fill"):
            fit_mode = "fit"
        logger.debug(f"Fit mode: {fit_mode}")

        logger.info("=== Image URL Plugin: Data fetch complete ===")
        return {"url": url, "fit_mode": fit_mode}

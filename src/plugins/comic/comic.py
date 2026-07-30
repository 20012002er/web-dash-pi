"""Comic plugin — returns the latest web comic strip URL, title, and caption.

Ported from the original OpenClaw-DashPi project. Instead of downloading and
composing a PIL image, ``get_data`` returns the comic panel's image URL, title,
and caption (along with the user's caption toggle and font size). The frontend
``dashboard.html`` fragment renders the strip with an ``<img>`` tag and the
caption below.
"""

import logging

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.comic.comic_parser import COMICS, get_panel

logger = logging.getLogger(__name__)


class Comic(BasePlugin):
    """Fetches the latest strip from a configured web comic and returns it for display."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['comics'] = list(COMICS)
        return template_params

    def get_data(self, settings, device_config):
        """Fetch the latest comic panel and return its URL, title, and caption."""
        comic = settings.get("comic")
        if not comic or comic not in COMICS:
            raise RuntimeError("Invalid comic provided.")

        show_caption = settings.get("titleCaption") == "true"
        caption_font_size = settings.get("fontSize") or 24

        try:
            comic_panel = get_panel(comic)
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("Failed to fetch comic '%s'", comic)
            raise RuntimeError(f"Failed to retrieve comic: {e}")

        return {
            "image_url": comic_panel.get("image_url", ""),
            "title": comic_panel.get("title", ""),
            "caption": comic_panel.get("caption", ""),
            "show_caption": show_caption,
            "caption_font_size": int(caption_font_size),
        }

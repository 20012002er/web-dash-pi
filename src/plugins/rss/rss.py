"""RSS plugin — returns parsed RSS/Atom feed headlines for the frontend.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image, ``get_data`` returns the feed title and a list of items (each with a
title, link, published date, and optional image URL), plus the user's
background/text colors. The frontend ``dashboard.html`` fragment renders the
title at the top and a scrollable list of items below.
"""

import html
import logging
import re

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)


class Rss(BasePlugin):
    """Parses an RSS/Atom feed and returns a list of headlines with optional thumbnails."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Fetch the RSS feed and return the headlines data."""
        title = settings.get("title")
        feed_url = settings.get("feedUrl")
        if not feed_url:
            raise RuntimeError("RSS Feed Url is required.")

        include_images = settings.get("includeImages") == "true"

        logger.info("Fetching RSS feed: %s", feed_url)
        items = self.parse_rss_feed(feed_url)
        logger.info("Parsed %d items from feed", len(items))

        # Map frontend-facing item keys; only include image_url when requested.
        result_items = []
        for item in items[:10]:
            result_items.append({
                "title": self._strip_html(item.get("title", "")),
                "link": item.get("link", ""),
                "published": item.get("published", ""),
                "image_url": item.get("image") if include_images else None,
            })

        return {
            "title": title or "",
            "items": result_items,
            "include_images": include_images,
            "background_color": settings.get("backgroundColor", "#ffffff"),
            "text_color": settings.get("textColor", "#000000"),
        }

    def parse_rss_feed(self, url, timeout=10):
        """Fetch and parse an RSS/Atom feed into a list of item dicts."""
        import feedparser

        session = get_http_session()
        resp = session.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        feed = feedparser.parse(resp.content)
        items = []

        for entry in feed.entries:
            item = {
                "title": html.unescape(entry.get("title", "")),
                "description": html.unescape(entry.get("description", "")),
                "published": entry.get("published", ""),
                "link": entry.get("link", ""),
                "image": None,
            }

            # Try to extract image from common RSS fields
            if "media_content" in entry and len(entry.media_content) > 0:
                item["image"] = entry.media_content[0].get("url")
            elif "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
                item["image"] = entry.media_thumbnail[0].get("url")
            elif "enclosures" in entry and len(entry.enclosures) > 0:
                item["image"] = entry.enclosures[0].get("url")

            items.append(item)

        return items

    @staticmethod
    def _strip_html(text):
        """Remove HTML tags and unescape entities from text."""
        clean = re.sub(r'<[^>]+>', '', text)
        return html.unescape(clean).strip()

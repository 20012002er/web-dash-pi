"""Art Museum plugin — fetches a random artwork for the frontend to display.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched a random artwork from the Metropolitan Museum of Art or the Art
Institute of Chicago, downloaded it via the adaptive image loader, and drew a
title/artist overlay with PIL. This web version keeps the Met/Chicago
fetching logic, classification filtering, and Met object-ID caching intact,
but returns the image URL and metadata as a dict so the frontend
``dashboard.html`` fragment can render the image with an HTML overlay.

``get_data`` returns:
    {image_url: str, title: str, artist: str, year: str, museum: str}
"""

import logging
import random

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

MET_SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
CHICAGO_API_URL = "https://api.artic.edu/api/v1/artworks"
CHICAGO_IIIF_URL = "https://www.artic.edu/iiif/2"


class ArtMuseum(BasePlugin):
    """Fetches a random artwork from the Met Museum or Art Institute of Chicago APIs."""

    def __init__(self, config, **deps):
        super().__init__(config, **deps)
        self._met_ids = None  # Cached list of Met object IDs with images

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {"required": False}
        template_params['style_settings'] = False
        return template_params

    def get_data(self, settings, device_config):
        """Fetch a random artwork URL and metadata for the frontend to render."""
        logger.info("=== Art Museum Plugin: Starting ===")

        museum = settings.get("museum", "both")
        show_title = settings.get("showTitle", "true") != "false"
        fit_mode = settings.get("fitMode", "fit")
        art_types = self._get_art_types(settings)

        # Pick source
        if museum == "both":
            source = random.choice(["met", "chicago"])
        else:
            source = museum

        logger.info("Fetching artwork from: %s (types: %s)", source, art_types)

        if source == "met":
            artwork = self._fetch_met_artwork(art_types)
            museum_name = "Metropolitan Museum of Art"
        else:
            artwork = self._fetch_chicago_artwork(art_types)
            museum_name = "Art Institute of Chicago"

        logger.info("Artwork: '%s' by %s", artwork['title'], artwork['artist'])

        if fit_mode not in ("fit", "fill"):
            fit_mode = "fit"

        logger.info("=== Art Museum Plugin: Complete ===")
        return {
            "image_url": artwork["image_url"],
            "title": artwork.get("title", "") or "Untitled",
            "artist": artwork.get("artist", ""),
            "year": artwork.get("date", ""),
            "museum": museum_name,
            "show_title": show_title,
            "fit_mode": fit_mode,
        }

    def _get_art_types(self, settings):
        """Get enabled art type filters from settings."""
        types = set()
        if settings.get("artPaintings", "true") != "false":
            types.add("paintings")
        if settings.get("artPhotos", "true") != "false":
            types.add("photos")
        if settings.get("artOthers", "true") != "false":
            types.add("others")
        # Default to all if none selected
        if not types:
            types = {"paintings", "photos", "others"}
        return types

    def _classify_met(self, classification):
        """Classify a Met artwork by its classification field."""
        if not classification:
            return "others"
        cl = classification.lower()
        if "paint" in cl:
            return "paintings"
        if "photograph" in cl or "photo" in cl:
            return "photos"
        return "others"

    def _classify_chicago(self, artwork_type):
        """Classify a Chicago artwork by its artwork_type_title field."""
        if not artwork_type:
            return "others"
        at = artwork_type.lower()
        if "paint" in at:
            return "paintings"
        if "photograph" in at or "photo" in at:
            return "photos"
        return "others"

    def _fetch_met_artwork(self, art_types):
        """Fetch a random artwork from the Metropolitan Museum of Art."""
        session = get_http_session()

        # Cache the list of object IDs with images
        if self._met_ids is None:
            logger.info("Fetching Met Museum object ID list (first time)...")
            resp = session.get(MET_SEARCH_URL, params={
                "hasImages": "true",
                "q": "*"
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            ids = data.get("objectIDs", [])
            if ids:
                self._met_ids = ids
                logger.info("Cached %d Met object IDs", len(self._met_ids))
            else:
                logger.warning("Met Museum API returned empty object ID list")

        if not self._met_ids:
            raise RuntimeError("No artworks found in Met Museum API.")

        # Try random objects until we find one with an image and matching type
        for attempt in range(20):
            obj_id = random.choice(self._met_ids)
            try:
                resp = session.get(f"{MET_OBJECT_URL}/{obj_id}", timeout=15)
                resp.raise_for_status()
                obj = resp.json()

                # Prefer small image (web-sized) over full primary (can be 4000px+).
                image_url = obj.get("primaryImageSmall") or obj.get("primaryImage", "")
                if not image_url:
                    logger.debug("Met object %s has no image, retrying...", obj_id)
                    continue

                classification = obj.get("classification", "")
                art_type = self._classify_met(classification)
                if art_type not in art_types:
                    logger.debug("Met object %s is '%s' (%s), skipping...", obj_id, classification, art_type)
                    continue

                return {
                    "title": obj.get("title", ""),
                    "artist": obj.get("artistDisplayName", ""),
                    "date": obj.get("objectDate", ""),
                    "image_url": image_url,
                }
            except Exception as e:
                logger.warning("Failed to fetch Met object %s: %s", obj_id, e)
                continue

        raise RuntimeError("Could not find a matching Met artwork after 20 attempts.")

    def _fetch_chicago_artwork(self, art_types):
        """Fetch a random artwork from the Art Institute of Chicago."""
        session = get_http_session()

        for attempt in range(20):
            page = random.randint(1, 5000)
            try:
                resp = session.get(CHICAGO_API_URL, params={
                    "page": page,
                    "limit": 1,
                    "fields": "id,title,artist_display,date_display,image_id,artwork_type_title",
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                artworks = data.get("data", [])
                if not artworks:
                    continue

                art = artworks[0]
                image_id = art.get("image_id")
                if not image_id:
                    logger.debug("Chicago artwork on page %s has no image_id, retrying...", page)
                    continue

                artwork_type = art.get("artwork_type_title", "")
                art_type = self._classify_chicago(artwork_type)
                if art_type not in art_types:
                    logger.debug("Chicago artwork on page %s is '%s' (%s), skipping...", page, artwork_type, art_type)
                    continue

                image_url = f"{CHICAGO_IIIF_URL}/{image_id}/full/1024,/0/default.jpg"

                return {
                    "title": art.get("title", ""),
                    "artist": art.get("artist_display", ""),
                    "date": art.get("date_display", ""),
                    "image_url": image_url,
                }
            except Exception as e:
                logger.warning("Failed to fetch Chicago artwork (page %s): %s", page, e)
                continue

        raise RuntimeError("Could not find a matching Chicago artwork after 20 attempts.")

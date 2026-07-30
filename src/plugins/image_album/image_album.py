"""Image Album plugin — displays photos from an Immich album.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched album metadata from Immich, picked a random asset, downloaded it via
the adaptive image loader, and rendered a PIL image. The web version fetches
the same metadata, picks a random asset, downloads the raw image bytes to
``static/images/saved/image_album_current.jpg``, and returns that URL so the
browser can render it directly. The ``generate_settings_template()`` override
is retained so the API key requirement (``IMMICH_KEY``) is declared.
"""

import logging
import os
from random import choice

from utils.http_client import get_http_session
from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class ImmichProvider:
    """Fetches album photos from a self-hosted Immich server."""

    def __init__(self, base_url: str, key: str):
        self.base_url = base_url.rstrip('/')
        self.key = key
        self.headers = {"x-api-key": self.key}
        self.session = get_http_session()

    def get_album_id(self, album: str) -> str:
        logger.debug(f"Fetching albums from {self.base_url}")
        r = self.session.get(f"{self.base_url}/api/albums", headers=self.headers, timeout=15)
        r.raise_for_status()
        albums = r.json()

        matching_albums = [a for a in albums if a["albumName"] == album]
        if not matching_albums:
            raise RuntimeError(f"Album '{album}' not found.")

        return matching_albums[0]["id"]

    def get_assets(self, album_id: str) -> list[dict]:
        """Fetch all assets from album."""
        all_items = []
        page_items = [1]
        page = 1

        logger.debug(f"Fetching assets from album {album_id}")
        max_pages = 100  # Safety limit to prevent infinite pagination
        while page_items and page <= max_pages:
            body = {
                "albumIds": [album_id],
                "size": 1000,
                "page": page
            }
            r2 = self.session.post(
                f"{self.base_url}/api/search/metadata", json=body, headers=self.headers, timeout=15
            )
            r2.raise_for_status()
            assets_data = r2.json()

            page_items = assets_data.get("assets", {}).get("items", [])
            all_items.extend(page_items)
            page += 1

        logger.debug(f"Found {len(all_items)} total assets in album")
        return all_items

    def download_image(self, album: str) -> tuple[bytes, str] | None:
        """Pick a random asset from the album and download its original bytes.

        Returns:
            Tuple of (image_bytes, extension) or None on error. The extension
            defaults to ``.jpg`` when the asset's original file name lacks one.
        """
        try:
            logger.info(f"Getting id for album '{album}'")
            album_id = self.get_album_id(album)
            logger.info(f"Getting assets from album id {album_id}")
            assets = self.get_assets(album_id)

            if not assets:
                logger.error(f"No assets found in album '{album}'")
                return None

        except Exception as e:
            logger.error(f"Error retrieving album data from {self.base_url}: {e}")
            return None

        # Select random asset
        selected_asset = choice(assets)
        asset_id = selected_asset["id"]
        asset_url = f"{self.base_url}/api/assets/{asset_id}/original"

        # Determine extension from the asset's original file name (fallback to .jpg)
        original_file_name = selected_asset.get("originalFileName", "")
        ext = os.path.splitext(original_file_name)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.bmp', '.tiff', '.heif', '.heic'):
            ext = '.jpg'

        logger.info(f"Selected random asset: {asset_id}")
        logger.debug(f"Downloading from: {asset_url}")

        try:
            r = self.session.get(asset_url, headers=self.headers, timeout=40)
            r.raise_for_status()
            return r.content, ext
        except Exception as e:
            logger.error(f"Failed to download image {asset_id} from Immich: {e}")
            return None


class ImageAlbum(BasePlugin):
    """Downloads a random photo from a configured Immich album and returns a served URL."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "Immich",
            "expected_key": "IMMICH_KEY"
        }
        return template_params

    def get_data(self, settings, device_config):
        """Fetch a random photo from the configured Immich album.

        Args:
            settings: Plugin settings dict containing ``albumProvider``,
                ``url``, ``album``, and ``fitMode``.
            device_config: Device configuration object, used to load the
                ``IMMICH_KEY`` environment variable.

        Returns:
            dict: ``{image_url: str, fit_mode: str}`` for the frontend.
        """
        logger.info("=== Image Album Plugin: Starting data fetch ===")

        img_bytes = None
        ext = '.jpg'
        album_provider = settings.get("albumProvider")
        logger.info(f"Album provider: {album_provider}")

        # Display mode: fit (letterbox), fill (crop), or blur (blurred background)
        fit_mode = settings.get('fitMode')
        if not fit_mode:
            if settings.get('padImage') == 'true':
                fit_mode = 'blur' if settings.get('backgroundOption', 'blur') == 'blur' else 'fit'
            else:
                fit_mode = 'fill'
        logger.debug(f"Settings: fit_mode={fit_mode}")

        match album_provider:
            case "Immich":
                key = device_config.load_env_key("IMMICH_KEY")
                if not key:
                    logger.error("Immich API Key not configured")
                    raise RuntimeError("Immich API Key not configured.")

                url = settings.get('url')
                if not url:
                    logger.error("Immich URL not provided")
                    raise RuntimeError("Immich URL is required.")

                album = settings.get('album')
                if not album:
                    logger.error("Album name not provided")
                    raise RuntimeError("Album name is required.")

                logger.info(f"Immich URL: {url}")
                logger.info(f"Album: {album}")

                provider = ImmichProvider(url, key)
                result = provider.download_image(album)

                if not result:
                    logger.error("Failed to retrieve image from Immich")
                    raise RuntimeError("Failed to load image, please check logs.")

                img_bytes, ext = result
            case _:
                logger.error(f"Unknown album provider: {album_provider}")
                raise RuntimeError(f"Unsupported album provider: {album_provider}")

        if not img_bytes:
            logger.error("Image bytes are empty after provider processing")
            raise RuntimeError("Failed to load image, please check logs.")

        # Persist the downloaded bytes to the served static directory so the
        # browser can load them. Reuse a stable filename so old copies are
        # overwritten on each refresh.
        saved_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "static", "images", "saved"
        )
        try:
            os.makedirs(saved_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create saved directory: {e}")
            raise RuntimeError("Failed to prepare image output directory.")

        dest_filename = f"image_album_current{ext}"
        dest_path = os.path.join(saved_dir, dest_filename)

        try:
            with open(dest_path, 'wb') as f:
                f.write(img_bytes)
            logger.debug(f"Saved image to: {dest_path}")
        except Exception as e:
            logger.error(f"Error saving image to {dest_path}: {e}")
            raise RuntimeError("Failed to load image, please check logs.")

        image_url = f"/static/images/saved/{dest_filename}"

        logger.info("=== Image Album Plugin: Data fetch complete ===")
        return {"image_url": image_url, "fit_mode": fit_mode}

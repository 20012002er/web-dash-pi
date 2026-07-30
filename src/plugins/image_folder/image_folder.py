"""Image Folder plugin — picks a random image from a local folder for the frontend to render.

Ported from the original OpenClaw-DashPi project. The original implementation
scanned a folder, picked a random image, and rendered a PIL image with the
configured fit mode. The web version scans the folder, picks a random image,
copies it to ``static/images/saved/`` so the browser can load it via a
``/static/...`` URL, and returns that URL along with the fit mode. Browsers
cannot load arbitrary local file paths, so copying to a served directory is the
pragmatic solution.
"""

from plugins.base_plugin.base_plugin import BasePlugin
import logging
import os
import random
import shutil

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (
    '.avif', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heif', '.heic'
)


def list_files_in_folder(folder_path):
    """Return a list of image file paths in the given folder, excluding hidden files."""
    image_files = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith(IMAGE_EXTENSIONS) and not f.startswith('.'):
                image_files.append(os.path.join(root, f))
    return image_files


class ImageFolder(BasePlugin):
    """Picks a random image from a folder and returns a browser-servable URL."""

    def get_data(self, settings, device_config):
        """Scan the configured folder, pick a random image, copy it to a served path.

        Args:
            settings: Plugin settings dict containing ``folder_path`` and ``fitMode``.
            device_config: Device configuration object (unused for this plugin).

        Returns:
            dict: ``{image_url: str, fit_mode: str}`` for the frontend.
        """
        logger.info("=== Image Folder Plugin: Starting data fetch ===")

        folder_path = settings.get('folder_path')
        if not folder_path:
            logger.error("No folder path provided in settings")
            raise RuntimeError("Folder path is required.")

        if not os.path.exists(folder_path):
            logger.error(f"Folder does not exist: {folder_path}")
            raise RuntimeError(f"Folder does not exist: {folder_path}")

        if not os.path.isdir(folder_path):
            logger.error(f"Path is not a directory: {folder_path}")
            raise RuntimeError(f"Path is not a directory: {folder_path}")

        logger.info(f"Scanning folder: {folder_path}")
        image_files = list_files_in_folder(folder_path)

        if not image_files:
            logger.warning(f"No image files found in folder: {folder_path}")
            raise RuntimeError(f"No image files found in folder: {folder_path}")

        logger.debug(f"Found {len(image_files)} image file(s) in folder")
        image_path = random.choice(image_files)
        logger.info(f"Selected random image: {os.path.basename(image_path)}")

        # Copy the selected image to the served static directory so the browser
        # can load it. Reuse a stable filename so old copies are overwritten.
        extension = os.path.splitext(image_path)[1].lower()
        saved_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "static", "images", "saved"
        )
        try:
            os.makedirs(saved_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create saved directory: {e}")
            raise RuntimeError("Failed to prepare image output directory.")

        dest_filename = f"image_folder_current{extension}"
        dest_path = os.path.join(saved_dir, dest_filename)

        try:
            shutil.copy2(image_path, dest_path)
            logger.debug(f"Copied image to: {dest_path}")
        except Exception as e:
            logger.error(f"Error copying image from {image_path}: {e}")
            raise RuntimeError("Failed to load image, please check logs.")

        image_url = f"/static/images/saved/{dest_filename}"

        # Display mode: fit (letterbox), fill (crop), or blur (blurred background)
        fit_mode = settings.get('fitMode')
        if not fit_mode:
            if settings.get('padImage') == 'true':
                fit_mode = 'blur' if settings.get('backgroundOption', 'blur') == 'blur' else 'fit'
            else:
                fit_mode = 'fill'
        logger.debug(f"Settings: fit_mode={fit_mode}")

        logger.info("=== Image Folder Plugin: Data fetch complete ===")
        return {"image_url": image_url, "fit_mode": fit_mode}

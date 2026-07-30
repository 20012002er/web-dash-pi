"""Image Upload plugin — displays user-uploaded images from local storage.

Ported from the original OpenClaw-DashPi project. The original implementation
loaded uploaded images with the adaptive image loader, applied fit/pad modes,
and optionally overlaid the filename via PIL. The web version selects an image
by index (or randomly), returns a browser-servable URL pointing at the file
already stored under ``static/images/saved/``, and lets the frontend render it
with CSS ``object-fit``. The disk reconciliation logic is retained so uploaded
files on disk are recovered into the settings list.
"""

from plugins.base_plugin.base_plugin import BasePlugin
import logging
import os
import random

logger = logging.getLogger(__name__)


class ImageUpload(BasePlugin):
    """Returns a URL pointing at one of the uploaded images for the frontend to render."""

    def get_data(self, settings, device_config):
        """Select an uploaded image and return its URL along with index/total info.

        Args:
            settings: Plugin settings dict containing ``imageFiles[]``,
                ``image_index``, ``randomize``, and ``fitMode``.
            device_config: Device configuration object, used to persist the
                next image index and reconcile with on-disk files.

        Returns:
            dict: ``{image_url: str, index: int, total: int, fit_mode: str}``
            for the frontend.
        """
        logger.info("=== Image Upload Plugin: Starting data fetch ===")

        # Ensure _previous_files is available (form POST doesn't include it)
        if '_previous_files' not in settings:
            stored = device_config.get_config("plugin_last_settings_image_upload", default={})
            settings['_previous_files'] = stored.get('_previous_files', [])

        # Reconcile: add any files on disk that aren't in settings (recovers from crashes)
        self._reconcile_with_disk(settings)

        # Get the current index — check stored settings if not in form POST
        img_index = settings.get("image_index")
        if img_index is None:
            stored = device_config.get_config("plugin_last_settings_image_upload", default={})
            img_index = stored.get("image_index", 0)
        image_locations = settings.get("imageFiles[]")

        if not image_locations:
            logger.error("No images uploaded")
            raise RuntimeError("No images provided.")

        # Coerce index to int in case it arrives as a string from form data
        try:
            img_index = int(img_index)
        except (TypeError, ValueError):
            img_index = 0

        logger.debug(f"Total uploaded images: {len(image_locations)}")
        logger.debug(f"Current index: {img_index}")

        if img_index >= len(image_locations):
            # Prevent Index out of range issues when file list has changed
            logger.warning(f"Index {img_index} out of range, resetting to 0")
            img_index = 0

        # Display mode: fit (letterbox), fill (crop), or blur (blurred background)
        fit_mode = settings.get('fitMode')
        if not fit_mode:
            if settings.get('padImage') == 'true':
                fit_mode = 'blur' if settings.get('backgroundOption', 'blur') == 'blur' else 'fit'
            else:
                fit_mode = 'fit'
        logger.debug(f"Settings: fit_mode={fit_mode}")

        is_random = settings.get('randomize') == 'true'
        logger.debug(f"Settings: randomize={is_random}, fit_mode={fit_mode}")

        if is_random:
            img_index = random.randrange(0, len(image_locations))
            logger.info(f"Random mode: Selected image index {img_index}")
        else:
            logger.info(f"Sequential mode: Loading image index {img_index}")

        selected_path = image_locations[img_index]

        if not os.path.exists(selected_path):
            logger.error(f"Image file not found: {selected_path}")
            raise RuntimeError("Selected image file is missing from disk.")

        # Build a browser-servable URL. Uploaded files live under
        # static/images/saved/, so map the absolute path back to /static/...
        image_url = self._path_to_url(selected_path)

        # Advance the index for the next sequential call (random mode keeps the same index)
        if not is_random:
            img_index = (img_index + 1) % len(image_locations)
            logger.debug(f"Next index will be: {img_index}")

        # Persist the new index back to the device config so sequential
        # cycling survives across refreshes.
        settings['image_index'] = img_index
        settings['_previous_files'] = list(image_locations)
        device_config.update_value("plugin_last_settings_image_upload", dict(settings))

        total = len(image_locations)

        logger.info("=== Image Upload Plugin: Data fetch complete ===")
        return {
            "image_url": image_url,
            "index": img_index,
            "total": total,
            "fit_mode": fit_mode,
        }

    @staticmethod
    def _path_to_url(file_path):
        """Map an absolute path under static/images/saved/ to a /static/ URL.

        Falls back to returning the raw path if the mapping cannot be determined.
        """
        # Locate the static directory relative to this file:
        # src/plugins/image_upload/image_upload.py -> src/static
        static_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), os.pardir, os.pardir, "static"
        ))
        abs_path = os.path.abspath(file_path)
        if abs_path.startswith(static_dir):
            rel = os.path.relpath(abs_path, static_dir).replace(os.sep, "/")
            return f"/static/{rel}"
        return file_path

    def _reconcile_with_disk(self, settings):
        """Add any files on disk that aren't in the settings list (recovers from crashes).

        Only adds files that weren't recently removed by the user. This prevents
        reconciliation from undoing intentional deletions via the web UI.
        """
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heif', '.heic', '.avif'}
        saved_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "static", "images", "saved"
        )

        if not os.path.isdir(saved_dir):
            return

        current_files = set(settings.get('imageFiles[]', []))
        current_basenames = {os.path.basename(f) for f in current_files}

        # Files the user previously had — if a file was in previous but not current,
        # the user intentionally removed it, so don't re-add it
        previous_files = set(settings.get('_previous_files', []))
        removed_basenames = {os.path.basename(f) for f in previous_files - current_files}

        added = 0
        for filename in sorted(os.listdir(saved_dir)):
            if filename.startswith('.'):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in image_extensions:
                continue
            if filename in current_basenames:
                continue
            if filename in removed_basenames:
                continue  # User intentionally removed this file
            full_path = os.path.join(saved_dir, filename)
            if 'imageFiles[]' not in settings:
                settings['imageFiles[]'] = []
            settings['imageFiles[]'].append(full_path)
            current_basenames.add(filename)
            added += 1

        if added:
            logger.info(f"Reconciled {added} image(s) from disk that were missing from settings")

    def cleanup(self, settings):
        """Delete all uploaded image files associated with this plugin instance."""
        image_locations = settings.get("imageFiles[]", [])
        if not image_locations:
            return

        for image_path in image_locations:
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                    logger.info(f"Deleted uploaded image: {image_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete uploaded image {image_path}: {e}")

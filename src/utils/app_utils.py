"""App utilities — paths, fonts, form parsing, and file handling.

Ported from the original OpenClaw-DashPi project. Retains path resolution,
font loading (PIL ImageFont), form parsing, file upload handling, and
filename sanitization. Display/IP/wifi helpers have been dropped since the
web dashboard no longer needs them.
"""

import logging
import os

from pathlib import Path
from PIL import Image, ImageOps
Image.MAX_IMAGE_PIXELS = 200_000_000  # Allow up to 200MP (default 89MP triggers warnings)

logger = logging.getLogger(__name__)

FONT_FAMILIES = {
    "Dogica": [{
        "font-weight": "normal",
        "file": "dogicapixel.ttf"
    },{
        "font-weight": "bold",
        "file": "dogicapixelbold.ttf"
    }],
    "Jost": [{
        "font-weight": "normal",
        "file": "Jost.ttf"
    },{
        "font-weight": "bold",
        "file": "Jost-SemiBold.ttf"
    }],
    "Napoli": [{
        "font-weight": "normal",
        "file": "Napoli.ttf"
    }],
    "DS-Digital": [{
        "font-weight": "normal",
        "file": os.path.join("DS-DIGI", "DS-DIGI.TTF")
    }]
}

FONTS = {
    "ds-gigi": "DS-DIGI.TTF",
    "napoli": "Napoli.ttf",
    "jost": "Jost.ttf",
    "jost-semibold": "Jost-SemiBold.ttf"
}


def sanitize_filename(filename):
    """Sanitize a filename while preserving spaces, parens, and other harmless characters.

    Blocks path traversal and null bytes but keeps the original appearance
    unlike werkzeug's secure_filename() which strips spaces and special chars.
    """
    # Strip directory components
    filename = os.path.basename(filename)
    # Remove null bytes
    filename = filename.replace('\x00', '')
    # Strip leading/trailing whitespace and dots (prevents hidden files / Windows issues)
    filename = filename.strip().strip('.')
    # Collapse path separators that might survive basename on edge cases
    filename = filename.replace('/', '_').replace('\\', '_')
    return filename or 'unnamed'


def resolve_path(file_path):
    """Resolve a relative path against the src directory."""
    src_dir = os.getenv("SRC_DIR")
    if src_dir is None:
        # Default to the src directory
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    src_path = Path(src_dir)
    return str(src_path / file_path)


def get_font(font_name, font_size=50, font_weight="normal"):
    """Load a bundled font by family name and weight.

    Args:
        font_name: Font family name — one of "Jost", "Dogica", "Napoli", "DS-Digital".
        font_size: Size in points (default 50).
        font_weight: "normal" or "bold" (default "normal"). Falls back to first
            available variant if the requested weight doesn't exist.

    Returns:
        PIL ImageFont.truetype instance, or None if font_name is not recognized.
    """
    from PIL import ImageFont

    if font_name in FONT_FAMILIES:
        font_variants = FONT_FAMILIES[font_name]

        font_entry = next((entry for entry in font_variants if entry["font-weight"] == font_weight), None)
        if font_entry is None:
            font_entry = font_variants[0]  # Default to first available variant

        if font_entry:
            font_path = resolve_path(os.path.join("static", "fonts", font_entry["file"]))
            return ImageFont.truetype(font_path, font_size)
        else:
            logger.warning(f"Requested font weight not found: font_name={font_name}, font_weight={font_weight}")
    else:
        logger.warning(f"Requested font not found: font_name={font_name}")

    return None


def get_font_path(font_name):
    """Return the absolute path for a font by its short name."""
    return resolve_path(os.path.join("static", "fonts", FONTS[font_name]))


def parse_form(request_form):
    """Parse Flask form data, handling the hidden+checkbox toggle pattern.

    For checkboxes with a hidden fallback (hidden value="false", checkbox value="true"),
    the form sends both values when checked. We take the LAST value for scalar fields,
    which is the checkbox value when checked, or the hidden value when unchecked.
    """
    request_dict = {}
    for key in request_form.keys():
        if key.endswith('[]'):
            request_dict[key] = request_form.getlist(key)
        else:
            values = request_form.getlist(key)
            request_dict[key] = values[-1] if values else ''
    return request_dict


def handle_request_files(request_files, form_data=None):
    """Process uploaded files: save to disk, fix EXIF orientation, return path map."""
    if form_data is None:
        form_data = {}
    allowed_file_extensions = {'pdf', 'png', 'avif', 'jpg', 'jpeg', 'gif', 'webp', 'heif', 'heic'}
    file_location_map = {}
    # handle existing file locations being provided as part of the form data
    for key in set(request_files.keys()):
        is_list = key.endswith('[]')
        if key in form_data:
            file_location_map[key] = form_data.getlist(key) if is_list else form_data.get(key)
    # add new files in the request
    for key, file in request_files.items(multi=True):
        is_list = key.endswith('[]')
        file_name = file.filename
        if not file_name:
            continue

        extension = os.path.splitext(file_name)[1].replace('.', '')
        if not extension or extension.lower() not in allowed_file_extensions:
            continue

        file_name = os.path.basename(file_name)

        file_save_dir = resolve_path(os.path.join("static", "images", "saved"))
        file_path = os.path.join(file_save_dir, file_name)

        # Save the raw upload to disk first (no PIL, no memory spike)
        file.save(file_path)

        # Fix EXIF orientation in-place for JPEGs
        # Skip for very large images to avoid OOM on Pi
        if extension in {'jpg', 'jpeg'}:
            try:
                with Image.open(file_path) as img:
                    w, h = img.size
                    megapixels = (w * h) / 1_000_000
                    if megapixels > 50:
                        logger.info(f"Skipping EXIF for {file_name} ({megapixels:.0f}MP) - too large")
                    else:
                        transposed = ImageOps.exif_transpose(img)
                        if transposed is not img:
                            transposed.save(file_path)
                            transposed.close()
                import gc; gc.collect()
            except Exception as e:
                logger.warning(f"EXIF processing error for {file_name}: {e}")

        if is_list:
            file_location_map.setdefault(key, [])
            file_location_map[key].append(file_path)
        else:
            file_location_map[key] = file_path
    return file_location_map

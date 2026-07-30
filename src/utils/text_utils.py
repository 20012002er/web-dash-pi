"""
Simplified text utilities for the web version of DashPi.

The original PIL-based version of this module (wrapping, binary-search
truncation against pixel width, multi-line drawing) is no longer needed
because the web frontend renders text in HTML/CSS rather than on PIL
images. These minimal helpers provide rough character-based estimates
that are useful for settings page previews where pixel-perfect metrics
are not required.
"""


def truncate_text(text, max_length):
    """Truncate text to max_length characters, appending an ellipsis if cut.

    Args:
        text: The string to truncate.
        max_length: Maximum number of characters (excluding the ellipsis)
            to keep. If the text is longer than max_length, it is cut to
            max_length characters and "..." is appended.

    Returns:
        The original text if it fits within max_length, otherwise the
        truncated text with a trailing ellipsis.
    """
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def get_text_dimensions(text, font_size):
    """Return an approximate (width, height) for a string at a given font size.

    This is a rough heuristic that does not load any font or measure glyphs:
    width is estimated as font_size * len(text) * 0.6 (an average character
    advance factor) and height as font_size * 1.2 (line box factor).

    Args:
        text: The string to estimate dimensions for.
        font_size: Font size in pixels (or points, depending on context).

    Returns:
        (width, height) tuple of approximate dimensions.
    """
    if not text:
        return (0, 0)
    width = font_size * len(text) * 0.6
    height = font_size * 1.2
    return (width, height)

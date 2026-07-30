"""
Simplified layout utilities for the web version of DashPi.

The original PIL-based version of this module (drawing rounded rectangles,
progress bars, dotted fills, decorative frames) is no longer needed because
the web frontend renders visuals in HTML/CSS. Only the pure-math grid
calculator is retained here, since it is useful for arranging plugin
previews on the settings page without depending on PIL.
"""


def calculate_grid(num_items, container_width, container_height, columns=None):
    """Compute evenly-spaced grid cells for a given number of items.

    Args:
        num_items: Number of items to lay out in the grid.
        container_width: Total width available for the grid.
        container_height: Total height available for the grid.
        columns: Optional fixed column count. If None, a roughly square
            grid is chosen automatically based on num_items.

    Returns:
        List of (x, y, w, h) tuples in pixels, one per item, ordered
        row-major (left-to-right, top-to-bottom). Each cell is the same
        size and fills the container with no spacing.
    """
    if num_items <= 0:
        return []

    if columns is None or columns <= 0:
        # Choose a roughly square layout: columns = ceil(sqrt(num_items))
        columns = 1
        while columns * columns < num_items:
            columns += 1

    rows = (num_items + columns - 1) // columns

    cell_w = container_width // columns if columns > 0 else container_width
    cell_h = container_height // rows if rows > 0 else container_height

    cells = []
    for i in range(num_items):
        row = i // columns
        col = i % columns
        x = col * cell_w
        y = row * cell_h
        cells.append((x, y, cell_w, cell_h))
    return cells

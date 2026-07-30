"""To-do list plugin — returns styled task lists for the frontend to render.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image, ``get_data`` returns the main title, a list of lists (each with a title
and items), the chosen list style, font size scale, and the user's
background/text colors. The frontend ``dashboard.html`` fragment lays out the
lists side by side or stacked depending on the viewport aspect ratio.
"""

import logging

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

# Font-size scale mapping kept here so the frontend receives a numeric scale.
FONT_SIZES = {
    "x-small": 0.7,
    "smaller": 0.8,
    "small": 0.9,
    "normal": 1,
    "large": 1.1,
    "larger": 1.2,
    "x-large": 1.3,
}


class TodoList(BasePlugin):
    """Builds one or more to-do lists with configurable bullet styles and fonts."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Build the to-do list structure from the configured list items."""
        lists = []
        list_titles = settings.get('list-title[]', []) or []
        list_contents = settings.get('list[]', []) or []
        for title, raw_list in zip(list_titles, list_contents):
            items = [line for line in raw_list.split('\n') if line.strip()]
            lists.append({
                'title': title or "",
                'items': items,
            })

        font_scale = FONT_SIZES.get(settings.get('fontSize', 'normal'), 1)
        list_style = settings.get('listStyle', 'disc')

        return {
            "title": settings.get('title') or "",
            "lists": lists,
            "list_style": list_style,
            "font_scale": font_scale,
            "background_color": settings.get("backgroundColor", "#ffffff"),
            "text_color": settings.get("textColor", "#000000"),
        }

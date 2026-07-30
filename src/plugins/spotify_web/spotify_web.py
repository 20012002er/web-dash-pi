"""Spotify Web Player plugin — embeds the Spotify Web Player via an iframe.

Ported from the original OpenClaw-DashPi project. The original managed a
Chromium kiosk process (Xorg + chromium-browser) that hijacked the Pi's
framebuffer; all of that subprocess/kiosk/session-management logic has been
removed for the web version. Instead, ``get_data`` returns the Spotify embed
URL (either the main player or a specific playlist), and the frontend
``dashboard.html`` embeds it in an iframe. The browser manages its own
cookies, so ``logged_in_hint`` is always True.

Note: Spotify may block iframe embedding via X-Frame-Options; the frontend
detects this and falls back to an "Open Spotify" link.
"""

import logging

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

SPOTIFY_URL = "https://open.spotify.com/"


class SpotifyWeb(BasePlugin):
    """Returns a Spotify Web Player embed URL for the frontend iframe."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        template_params['hide_refresh_interval'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Return the Spotify embed URL based on the configured playlist.

        Returns:
            dict with keys: embed_url (str), logged_in_hint (bool).
            If a playlist URI/ID is configured, it is converted to the
            Spotify embed URL; otherwise the main player URL is returned.
        """
        playlist = settings.get("spotifyPlaylist") or settings.get("playlistUri")
        embed_url = self._build_embed_url(playlist)
        logger.info("Spotify embed URL: %s", embed_url)

        return {
            "embed_url": embed_url,
            "logged_in_hint": True,
        }

    @staticmethod
    def _build_embed_url(playlist):
        """Convert a playlist URI/URL/ID into a Spotify embed URL.

        Accepts:
          - spotify:playlist:<id>
          - https://open.spotify.com/playlist/<id>
          - bare playlist id
        Falls back to the main player URL when no playlist is given.
        """
        if not playlist:
            return SPOTIFY_URL

        playlist_id = None
        if playlist.startswith("spotify:playlist:"):
            playlist_id = playlist.split("spotify:playlist:", 1)[1]
        elif "/playlist/" in playlist:
            playlist_id = playlist.split("/playlist/", 1)[1].split("?")[0]
        elif playlist.startswith(("https://", "http://")):
            # Some other Spotify URL (album, artist, etc.) — pass through.
            return playlist
        else:
            playlist_id = playlist

        if not playlist_id:
            return SPOTIFY_URL
        return f"https://open.spotify.com/embed/playlist/{playlist_id}"

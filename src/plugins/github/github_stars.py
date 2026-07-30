"""GitHub stars helper — fetches repository star count via the REST API.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image with the current star count, ``get_data`` returns a JSON-serializable
dict with the repository name, the current star count, and a history list
of {date, count} points. The GitHub REST API only exposes the current
stargazer count (no historical series), so ``history`` is seeded with a
single point for today; the frontend ``dashboard.html`` renders a line
chart via Chart.js.
"""

import logging
from datetime import date

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)


def get_data(plugin, settings, device_config):
    """Fetch the repository's current star count and return a data dict.

    Returns:
        dict with keys: type, username, repository, history, current_count.
        ``history`` is a list of {date, count} dicts (one point for today
        since the REST API exposes no historical series).
    """
    username = settings.get('githubUsername')
    repository = settings.get('githubRepository')

    if not username or not repository:
        raise RuntimeError("GitHub repository is required.")

    full_repo = f"{username}/{repository}"

    try:
        current_count = fetch_stars(full_repo)
    except Exception as e:
        logger.error("GitHub REST request failed: %s", str(e))
        raise RuntimeError("GitHub request failure, please check logs")

    today_str = date.today().isoformat()
    history = [{"date": today_str, "count": current_count}]

    return {
        "type": "stars",
        "username": username,
        "repository": full_repo,
        "history": history,
        "current_count": current_count,
        "background_color": settings.get("backgroundColor", "#ffffff"),
        "text_color": settings.get("textColor", "#000000"),
    }


# -------------------------
# Helper functions
# -------------------------

def fetch_stars(github_repository):
    """GET the repository metadata from the GitHub REST API and return the star count."""
    url = f"https://api.github.com/repos/{github_repository}"
    headers = {"Accept": "application/json"}

    session = get_http_session()
    response = session.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        data = response.json()
    else:
        logger.error(
            "GitHub Stars Plugin: Error: %s - %s",
            response.status_code, response.text,
        )
        data = {"stargazers_count": 0}

    return int(data['stargazers_count'])

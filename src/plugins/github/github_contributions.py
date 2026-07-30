"""GitHub contributions helper — fetches the contribution calendar via GraphQL.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
heatmap, ``get_data`` returns a JSON-serializable dict with the raw
contribution weeks/days (each day carrying its date and count), the total
contributions, and the current streak. The frontend ``dashboard.html``
renders the GitHub-style green-square heatmap via CSS grid using the
user-configured colors.
"""

import logging
from datetime import date, timedelta

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

GRAPHQL_QUERY = """
query($username: String!) {
  user(login: $username) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""

# Default GitHub heatmap palette (empty → darkest green).
DEFAULT_COLORS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]


def get_data(plugin, settings, device_config):
    """Fetch the user's contribution calendar and return a data dict.

    Returns:
        dict with keys: type, username, weeks, total, streak, colors.
        ``weeks`` is a list of weeks, each a list of {date, count} day dicts.
    """
    api_key = device_config.load_env_key("GITHUB_SECRET")
    if not api_key:
        raise RuntimeError("GitHub API Key not configured.")

    github_username = settings.get("githubUsername")
    if not github_username:
        raise RuntimeError("GitHub username is required.")

    colors = settings.get("contributionColor[]") or DEFAULT_COLORS

    data = fetch_contributions(github_username, api_key)
    weeks = extract_weeks(data)
    total = extract_total(data)
    streak = calculate_current_streak(weeks)

    return {
        "type": "contributions",
        "username": github_username,
        "weeks": weeks,
        "total": total,
        "streak": streak,
        "colors": colors,
        "background_color": settings.get("backgroundColor", "#ffffff"),
        "text_color": settings.get("textColor", "#000000"),
    }


# -------------------------
# Helper functions
# -------------------------

def fetch_contributions(username, api_key):
    """POST the GraphQL query to GitHub and return the parsed JSON response."""
    url = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {api_key}"}
    variables = {"username": username}
    session = get_http_session()
    resp = session.post(
        url,
        json={"query": GRAPHQL_QUERY, "variables": variables},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def extract_weeks(data):
    """Return the contribution weeks as a list of lists of {date, count} dicts."""
    calendar = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = []
    for week in calendar["weeks"]:
        days = []
        for day in week["contributionDays"]:
            days.append({
                "date": day["date"],
                "count": day["contributionCount"],
            })
        weeks.append(days)
    return weeks


def extract_total(data):
    """Return the total contributions from the calendar."""
    calendar = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return int(calendar["totalContributions"])


def calculate_current_streak(weeks):
    """Return the length of the current consecutive-day contribution streak.

    Walks the days in reverse chronological order, counting consecutive days
    with at least one contribution. The streak ends on the first zero day
    (today counts even if it has zero contributions, matching GitHub's UI).
    """
    days = [day for week in weeks for day in week]
    if not days:
        return 0

    # Sort chronologically by date.
    days = sorted(days, key=lambda d: d["date"])

    today = date.today()
    yesterday = today - timedelta(days=1)

    last_date = date.fromisoformat(days[-1]["date"])
    # If the most recent contribution day is older than yesterday, no streak.
    if last_date < yesterday:
        return 0

    streak = 0
    for day in reversed(days):
        day_date = date.fromisoformat(day["date"])
        if day["count"] > 0:
            streak += 1
        elif day_date >= yesterday:
            # Today may be zero (user hasn't contributed yet today); keep walking.
            continue
        else:
            break
    return streak

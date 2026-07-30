"""GitHub sponsors helper — fetches sponsorships-as-maintainer via GraphQL.

Ported from the original OpenClaw-DashPi project. Instead of rendering a PIL
image with the monthly earnings total, ``get_data`` returns a JSON-serializable
dict with the list of sponsors (each carrying a display name, an avatar URL,
and their tier name) plus the total sponsor count. The frontend
``dashboard.html`` renders the sponsor avatars and names as a grid.

Note: the GraphQL ``sponsorshipsAsMaintainer`` connection does not expose
avatar URLs directly, so we synthesize them from each sponsor's login using
GitHub's public avatar endpoint.
"""

import logging

from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

GRAPHQL_QUERY = """
query($username: String!) {
  user(login: $username) {
    sponsorshipsAsMaintainer(first: 100) {
      totalCount
      nodes {
        createdAt
        sponsorEntity {
          ... on User {
            login
            name
          }
          ... on Organization {
            login
            name
          }
        }
        tier {
          name
          monthlyPriceInCents
        }
      }
    }
    estimatedNextSponsorsPayoutInCents
  }
}
"""


def get_data(plugin, settings, device_config):
    """Fetch the user's sponsorships and return a data dict.

    Returns:
        dict with keys: type, username, sponsors, total_count.
        ``sponsors`` is a list of {name, avatar_url, tier} dicts.
    """
    api_key = device_config.load_env_key("GITHUB_SECRET")
    if not api_key:
        raise RuntimeError("GitHub API Key not configured.")

    github_username = settings.get("githubUsername")
    if not github_username:
        raise RuntimeError("GitHub username is required.")

    data = fetch_sponsorships(github_username, api_key)
    sponsors = extract_sponsors(data)
    total_count = extract_total_count(data)

    return {
        "type": "sponsors",
        "username": github_username,
        "sponsors": sponsors,
        "total_count": total_count,
        "background_color": settings.get("backgroundColor", "#ffffff"),
        "text_color": settings.get("textColor", "#000000"),
    }


# -------------------------
# Helper functions
# -------------------------

def fetch_sponsorships(username, api_key):
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
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(f"GitHub API returned errors: {data['errors']}")

    logger.debug("Fetched sponsor data for %s", username)
    return data


def extract_sponsors(data):
    """Return a list of {name, avatar_url, tier} sponsor dicts from the response."""
    nodes = data["data"]["user"]["sponsorshipsAsMaintainer"]["nodes"]
    sponsors = []
    for node in nodes:
        entity = node.get("sponsorEntity") or {}
        login = entity.get("login") or ""
        name = entity.get("name") or login
        tier = (node.get("tier") or {}).get("name") or ""
        sponsors.append({
            "name": name,
            "avatar_url": f"https://github.com/{login}.png" if login else "",
            "tier": tier,
        })
    return sponsors


def extract_total_count(data):
    """Return the total number of sponsors from the response."""
    return int(data["data"]["user"]["sponsorshipsAsMaintainer"]["totalCount"])

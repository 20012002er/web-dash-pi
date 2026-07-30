"""Astro Targets plugin — tonight's best DSO imaging targets for backyard astrophotography.

Ported from the original OpenClaw-DashPi project. The original implementation
used Skyfield to compute each target's altitude/azimuth across the night,
filtered by a user-defined horizon profile, scored the visible targets, and
rendered the ranked list as a dark-themed PIL image. This web version keeps
all the astronomical calculation, horizon filtering, scoring, and equipment
matching logic intact, but returns the ranked targets and moon info as a
JSON-serializable dict so the frontend ``dashboard.html`` fragment can render
the dark-themed list with CSS.

``get_data`` returns:
    {
        "targets": [{name, type, best_time, altitude, score, equipment}, ...],
        "moon_phase": str,
        "moon_illumination": float,
        "moon_alt": float,
        "observation_window": {"start": str, "end": str},
        "date": str,
        "background_color": str,
        "text_color": str,
    }

Note: requires the ``skyfield`` and ``numpy`` packages (not in the base
requirements.txt — install separately). The ``de421.bsp`` ephemeris file is
auto-downloaded to ``resources/`` on first run.
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

# Equipment profiles: name, FOV width/height in degrees
EQUIPMENT_PROFILES = [
    {"name": "ZS61 + ASI2600MM", "fov_w": 3.74, "fov_h": 2.50},
    {"name": "SeeStar S50", "fov_w": 2.0, "fov_h": 1.3},
    {"name": "FF107 + ASI2600MM", "fov_w": 1.93, "fov_h": 1.29},
    {"name": "ZS61 + ASI174MM", "fov_w": 1.80, "fov_h": 1.13},
    {"name": "FF107 + ASI174MM", "fov_w": 0.93, "fov_h": 0.58},
]

# Default horizon profile (Steven's backyard)
DEFAULT_HORIZON = [
    {"az": 0, "alt": 50},
    {"az": 45, "alt": 50},
    {"az": 90, "alt": 45},
    {"az": 135, "alt": 20},
    {"az": 180, "alt": 15},
    {"az": 225, "alt": 15},
    {"az": 270, "alt": 20},
    {"az": 315, "alt": 50},
]

# DSO type display info: label, icon color
TYPE_INFO = {
    "emission_nebula": ("Emission Neb.", "#e74c3c"),
    "reflection_nebula": ("Reflection Neb.", "#5dade2"),
    "planetary_nebula": ("Planetary Neb.", "#2ecc71"),
    "dark_nebula": ("Dark Nebula", "#7f8c8d"),
    "supernova_remnant": ("SNR", "#e67e22"),
    "galaxy": ("Galaxy", "#f1c40f"),
    "galaxy_group": ("Galaxy Group", "#f39c12"),
    "open_cluster": ("Open Cluster", "#3498db"),
    "globular_cluster": ("Globular Cluster", "#9b59b6"),
}

# Moon phase names
MOON_PHASES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]

# Cache for catalog and ephemeris
_catalog_cache = None
_ephemeris_cache = None


def _load_catalog(plugin_dir):
    """Load the curated DSO catalog from resources/targets.json."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    catalog_path = os.path.join(plugin_dir, "resources", "targets.json")
    with open(catalog_path, "r") as f:
        _catalog_cache = json.load(f)
    logger.info("Loaded %d DSO targets from catalog", len(_catalog_cache))
    return _catalog_cache


def _get_ephemeris(plugin_dir):
    """Load or download the de421.bsp ephemeris file."""
    global _ephemeris_cache
    if _ephemeris_cache is not None:
        return _ephemeris_cache
    from skyfield.api import Loader
    resources_dir = os.path.join(plugin_dir, "resources")
    load = Loader(resources_dir)
    _ephemeris_cache = load("de421.bsp")
    return _ephemeris_cache


def _get_horizon_alt(horizon_profile, azimuth):
    """Interpolate minimum altitude from horizon profile at given azimuth (0-360)."""
    az = azimuth % 360
    points = sorted(horizon_profile, key=lambda p: p["az"])
    # Wrap around: add copy of first point at 360
    wrapped = points + [{"az": points[0]["az"] + 360, "alt": points[0]["alt"]}]

    for i in range(len(wrapped) - 1):
        a1, a2 = wrapped[i]["az"], wrapped[i + 1]["az"]
        if a1 <= az <= a2:
            frac = (az - a1) / (a2 - a1) if a2 != a1 else 0
            return wrapped[i]["alt"] + frac * (wrapped[i + 1]["alt"] - wrapped[i]["alt"])
        # Handle wrap for az < first point
        if i == 0 and az < a1:
            prev = points[-1]
            a0 = prev["az"] - 360
            frac = (az - a0) / (a1 - a0) if a1 != a0 else 0
            return prev["alt"] + frac * (points[0]["alt"] - prev["alt"])

    return points[-1]["alt"]


def _compute_tonight_window(topos, eph, ts, date):
    """Compute astronomical twilight dusk (evening) to dawn (morning) using Skyfield."""
    from skyfield import almanac

    # Search from noon today to noon tomorrow to find dusk/dawn
    t0 = ts.utc(date.year, date.month, date.day, 12)
    t1 = ts.utc(date.year, date.month, date.day + 1, 12)

    # Astronomical twilight: sun at -18 degrees
    f = almanac.dark_twilight_day(eph, topos)
    times, events = almanac.find_discrete(t0, t1, f)

    # dark_twilight_day returns events:
    # 0 = night (sun below -18), 1 = astronomical twilight, 2 = nautical, 3 = civil, 4 = day
    # We want: transition TO 0 (dusk) and transition FROM 0 (dawn)
    dusk_idx = None
    dawn_idx = None
    for i, e in enumerate(events):
        if e == 0 and dusk_idx is None:
            dusk_idx = i
        if dusk_idx is not None and e > 0 and dawn_idx is None:
            dawn_idx = i

    if dusk_idx is None or dawn_idx is None:
        # Fallback: use 9pm to 5am UTC (rough)
        logger.warning("Could not compute twilight times, using fallback")
        return ts.utc(date.year, date.month, date.day + 1, 1), ts.utc(date.year, date.month, date.day + 1, 11)

    return times[dusk_idx], times[dawn_idx]


def _compute_moon_info(observer_pos, eph, ts, t_mid):
    """Compute moon illumination percentage and phase name.

    observer_pos should be earth + topos (a Skyfield VectorSum).
    """
    from skyfield import almanac
    moon = eph["moon"]

    # Moon phase angle (0-360)
    phase_angle = almanac.moon_phase(eph, t_mid).degrees
    # Illumination from phase angle
    illumination = (1 - math.cos(math.radians(phase_angle))) / 2 * 100

    # Phase name
    idx = int((phase_angle + 22.5) / 45) % 8
    phase_name = MOON_PHASES[idx]

    # Moon position at mid-observation
    apparent = observer_pos.at(t_mid).observe(moon).apparent()
    moon_alt, moon_az, _ = apparent.altaz()

    return {
        "illumination": illumination,
        "phase_name": phase_name,
        "alt": moon_alt.degrees,
        "az": moon_az.degrees,
    }


def _build_time_array(ts, dusk, dawn):
    """Build a vectorized Skyfield time array for the night at 30-min intervals."""
    import numpy as np
    dusk_tt = dusk.tt
    dawn_tt = dawn.tt
    interval = 30 / (24 * 60)  # 30 min in days
    num_steps = max(1, int((dawn_tt - dusk_tt) / interval))
    jd_array = np.array([dusk_tt + i * interval for i in range(num_steps + 1)])
    return ts.tt(jd=jd_array), num_steps + 1


def _compute_all_visibilities(catalog, observer_pos, t_array, num_steps, horizon_profile):
    """Compute visibility for all targets using vectorized Skyfield calls.

    Returns dict of target_id -> {peak_alt, total_minutes, best_time_idx} for visible targets.
    """
    from skyfield.api import Star

    # Pre-compute observer position at all times (vectorized)
    obs_at = observer_pos.at(t_array)

    results = {}
    for target in catalog:
        star = Star(ra_hours=target["ra_hours"], dec_degrees=target["dec_degrees"])

        # Vectorized observe: computes all time steps at once
        apparent = obs_at.observe(star).apparent()
        alt, az, _ = apparent.altaz()

        # alt.degrees and az.degrees are now numpy arrays
        alt_arr = alt.degrees
        az_arr = az.degrees

        peak_alt = -90.0
        visible_minutes = 0
        best_idx = 0

        for i in range(num_steps):
            min_alt = _get_horizon_alt(horizon_profile, float(az_arr[i]))
            if alt_arr[i] > min_alt:
                visible_minutes += 30
                if alt_arr[i] > peak_alt:
                    peak_alt = float(alt_arr[i])
                    best_idx = i

        if visible_minutes > 0:
            results[target["id"]] = {
                "peak_alt": peak_alt,
                "total_minutes": visible_minutes,
                "best_time_idx": best_idx,
            }

    return results


def _best_equipment(target, equipment_profiles):
    """Find the best equipment setup for a target based on FOV matching.

    Object should fill 30-80% of the shorter FOV axis for optimal framing.
    """
    size_deg = target.get("size_arcmin", 10) / 60.0
    best_name = None
    best_score = -1

    for profile in equipment_profiles:
        shorter_fov = min(profile["fov_w"], profile["fov_h"])
        fill_fraction = size_deg / shorter_fov

        # Ideal fill: 30-80% of shorter axis. Score peaks at 50%.
        if 0.1 <= fill_fraction <= 1.5:
            # Distance from ideal 0.5 fill
            score = 1.0 - abs(fill_fraction - 0.5) / 0.5
            if score > best_score:
                best_score = score
                best_name = profile["name"]

    if best_name is None:
        # Default to widest FOV if nothing matches well
        best_name = max(equipment_profiles, key=lambda p: p["fov_w"])["name"]

    return best_name


def _rank_targets(visible_targets):
    """Rank targets by combined score: peak altitude, visibility time, brightness."""
    for t in visible_targets:
        vis = t["visibility"]
        # Normalize components (0-1 scale)
        alt_score = vis["peak_alt"] / 90.0
        time_score = min(vis["total_minutes"] / 360, 1.0)  # Cap at 6 hours
        # Brighter = better (lower magnitude = brighter)
        mag = t.get("magnitude") or 10
        mag_score = max(0, 1.0 - (mag - 3) / 10.0)

        t["score"] = alt_score * 0.4 + time_score * 0.4 + mag_score * 0.2

    return sorted(visible_targets, key=lambda t: t["score"], reverse=True)


class AstroTargets(BasePlugin):
    """Shows tonight's best deep sky imaging targets filtered by sky window and equipment."""

    def __init__(self, config, **dependencies):
        super().__init__(config, **dependencies)
        self._cached_results = None
        self._cache_date = None

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        return template_params

    def get_data(self, settings, device_config):
        """Compute tonight's ranked DSO targets and return them as a dict."""
        from skyfield.api import Loader, wgs84

        timezone_name = device_config.get_config("timezone", default="America/Chicago")

        # Parse settings
        lat = float(settings.get("latitude", "32.7767"))
        lon = float(settings.get("longitude", "-96.7970"))
        max_targets = int(settings.get("maxTargets", "4"))
        horizon_json = settings.get("horizonProfile", "")
        enabled_types = self._get_enabled_types(settings)
        enabled_equipment = self._get_enabled_equipment(settings)

        # Parse horizon profile
        horizon_profile = DEFAULT_HORIZON
        if horizon_json:
            try:
                horizon_profile = json.loads(horizon_json)
            except (json.JSONDecodeError, TypeError):
                pass

        # Equipment profiles filtered by user selection
        equipment = [p for p in EQUIPMENT_PROFILES if p["name"] in enabled_equipment]
        if not equipment:
            equipment = EQUIPMENT_PROFILES

        # Compute targets
        plugin_dir = self.get_plugin_dir()
        catalog = _load_catalog(plugin_dir)
        eph = _get_ephemeris(plugin_dir)

        # Setup Skyfield
        resources_dir = os.path.join(plugin_dir, "resources")
        load = Loader(resources_dir)
        ts = load.timescale()
        topos = wgs84.latlon(lat, lon)
        earth = eph["earth"]
        observer_pos = earth + topos  # For observe() calls

        # Get current date in user's timezone
        import pytz
        tz = pytz.timezone(timezone_name)
        now = datetime.now(tz)

        # Use today's date for "tonight" (if before noon, use yesterday)
        if now.hour < 12:
            date = (now - timedelta(days=1)).date()
        else:
            date = now.date()

        # Check cache (include filters so changed settings bust the cache)
        cache_key = (date, lat, lon, frozenset(enabled_types), frozenset(e["name"] for e in equipment))
        if self._cached_results is not None and self._cache_date == cache_key:
            ranked, moon_info, dusk, dawn = self._cached_results
        else:
            # Compute tonight's window
            dusk, dawn = _compute_tonight_window(topos, eph, ts, date)

            # Moon info at mid-night
            t_mid = ts.tt(jd=(dusk.tt + dawn.tt) / 2)
            moon_info = _compute_moon_info(observer_pos, eph, ts, t_mid)

            # Filter catalog by enabled types
            filtered = [t for t in catalog if t.get("type", "") in enabled_types]

            # Compute visibility for all targets (vectorized)
            t_array, num_steps = _build_time_array(ts, dusk, dawn)
            vis_map = _compute_all_visibilities(filtered, observer_pos, t_array, num_steps, horizon_profile)

            # Build a list of (time_utc_datetime) for best-time lookups
            time_list = [t_array[i].utc_datetime() for i in range(num_steps)]

            visible = []
            for target in filtered:
                vis = vis_map.get(target["id"])
                if vis is not None:
                    entry = dict(target)
                    entry["visibility"] = vis
                    entry["equipment"] = _best_equipment(target, equipment)
                    # Best time = the 30-min slot where peak altitude occurs
                    best_idx = vis.get("best_time_idx", 0)
                    if 0 <= best_idx < len(time_list):
                        entry["best_time"] = time_list[best_idx].astimezone(tz).isoformat()
                    else:
                        entry["best_time"] = None
                    visible.append(entry)

            ranked = _rank_targets(visible)
            self._cached_results = (ranked, moon_info, dusk, dawn)
            self._cache_date = cache_key
            logger.info("Computed %d visible targets for %s (of %d filtered)", len(ranked), date, len(filtered))

        top_targets = ranked[:max_targets]

        # Serialize the targets for the frontend
        result_targets = []
        for t in top_targets:
            vis = t.get("visibility", {})
            type_info = TYPE_INFO.get(t.get("type", ""), ("", "#888888"))
            result_targets.append({
                "id": t.get("id", ""),
                "name": t.get("name", "") or t.get("constellation", ""),
                "type": t.get("type", ""),
                "type_label": type_info[0],
                "type_color": type_info[1],
                "constellation": t.get("constellation", ""),
                "magnitude": t.get("magnitude"),
                "best_time": t.get("best_time"),
                "altitude": round(vis.get("peak_alt", 0), 1),
                "visible_minutes": vis.get("total_minutes", 0),
                "score": round(t.get("score", 0), 3),
                "equipment": t.get("equipment", ""),
            })

        return {
            "targets": result_targets,
            "moon_phase": moon_info["phase_name"],
            "moon_illumination": round(moon_info["illumination"], 1),
            "moon_alt": round(moon_info["alt"], 1),
            "observation_window": {
                "start": dusk.utc_datetime().astimezone(tz).isoformat(),
                "end": dawn.utc_datetime().astimezone(tz).isoformat(),
            },
            "date": date.isoformat(),
            "background_color": settings.get("backgroundColor", "#1a1a2e"),
            "text_color": settings.get("textColor", "#e8e8e8"),
        }

    def _get_enabled_types(self, settings):
        """Get set of enabled DSO types from settings."""
        all_types = set(TYPE_INFO.keys())
        enabled = set()
        for t in all_types:
            key = f"type_{t}"
            if settings.get(key, "true") in ("true", True, "on", "1"):
                enabled.add(t)
        return enabled if enabled else all_types

    def _get_enabled_equipment(self, settings):
        """Get set of enabled equipment profile names from settings."""
        all_names = {p["name"] for p in EQUIPMENT_PROFILES}
        enabled = set()
        for p in EQUIPMENT_PROFILES:
            key = f"equip_{p['name'].replace(' ', '_').replace('+', '')}"
            if settings.get(key, "true") in ("true", True, "on"):
                enabled.add(p["name"])
        return enabled if enabled else all_names

"""ISS Tracker plugin — displays the International Space Station's real-time position.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched TLE data from CelesTrak, computed the ISS position via SGP4,
predicted visible passes via Skyfield (with an N2YO API fallback), fetched
the crew count from Open Notify, reverse-geocoded the sub-satellite point
against a bundled landmarks list, and rendered everything on a PIL world
map. This web version keeps ALL of that computation, caching, and
thread-safety intact, but returns the position, ground track, next pass,
crew count, and location name as a JSON-serializable dict so the frontend
``dashboard.html`` fragment can render the tracker on a Leaflet.js map.

``get_data`` returns:
    {
        "iss_position": {lat, lng, altitude_km, speed_kmh},
        "ground_track": [{lat, lng}, ...],
        "next_pass": {start_time, max_elevation, duration, visible} or null,
        "crew_count": int,
        "location_name": str,
        "is_passing": bool,
        "units": str,
        "observer": {lat, lng, city},
    }

Note: position computation uses ``sgp4`` directly. Pass prediction uses
``skyfield`` (with an N2YO API fallback if configured). ``sgp4`` and
``skyfield`` are not in the base requirements.txt — install them separately.
The ``de421.bsp`` ephemeris is auto-downloaded by Skyfield on first use.
"""

import json
import logging
import math
import os
import threading
import time as time_module
from datetime import datetime, timezone, timedelta

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
CREW_URL = "https://api.open-notify.org/astros.json"
TLE_CACHE_MAX_AGE = 6 * 3600  # 6 hours
EARTH_RADIUS_KM = 6371.0
ISS_CATALOG_NUMBER = 25544

# Mode trigger thresholds
PREPASS_TRIGGER_DEFAULT = 20  # minutes before pass
POSTPASS_DURATION = 5  # minutes after pass

# Cache refresh intervals (seconds)
PASS_REFRESH_INTERVAL = 300    # 5 minutes
CREW_REFRESH_INTERVAL = 1800   # 30 minutes
CREW_RETRY_INTERVAL = 300      # 5 minutes (when API is down)
TRACK_REFRESH_INTERVAL = 30    # 30 seconds
GEOCODE_MOVE_THRESHOLD = 0.5   # degrees before re-geocoding


class ISSTracker(BasePlugin):
    """Tracks the ISS using TLE data and returns its position, pass predictions, and crew info."""

    def __init__(self, config, **dependencies):
        super().__init__(config, **dependencies)
        self._lock = threading.Lock()

        # Cached heavy data
        self._cached_passes = None
        self._last_pass_fetch_time = 0

        self._cached_crew_count = 0
        self._last_crew_fetch_time = 0

        # Cached ground track points
        self._cached_ground_track = None
        self._last_track_time = 0

        # Cached reverse geocode
        self._cached_over_text = None
        self._over_text_position = None

        # Loaded-once resources
        self._landmarks = None

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        template_params['hide_refresh_interval'] = True
        template_params['api_key'] = {
            "required": False,
            "service": "N2YO",
            "expected_key": "N2YO_SECRET"
        }
        return template_params

    def _get_landmarks(self):
        """Load landmarks.json once and cache in memory."""
        if self._landmarks is None:
            landmarks_path = os.path.join(self.get_plugin_dir(), "resources", "landmarks.json")
            try:
                with open(landmarks_path, "r") as f:
                    self._landmarks = json.load(f)
                logger.info("Loaded %d landmarks", len(self._landmarks))
            except Exception:
                self._landmarks = []
        return self._landmarks

    def get_data(self, settings, device_config):
        """Compute the current ISS state and return it as a JSON-serializable dict."""
        lat = _parse_float(settings.get("latitude"), None)
        lon = _parse_float(settings.get("longitude"), None)

        # Fall back to weather plugin location if not configured
        weather_city = ""
        if lat is None or lon is None:
            w_lat, w_lon, weather_city = _find_weather_location(device_config)
            if lat is None:
                lat = w_lat
            if lon is None:
                lon = w_lon

        units = settings.get("units", "metric")
        prepass_minutes = _parse_int(
            settings.get("prepassTrigger"), PREPASS_TRIGGER_DEFAULT
        )

        tle_cache_path = os.path.join(self.get_plugin_dir(), "iss_tle_cache.json")
        tle_lines = _load_tle(tle_cache_path)

        now_utc = datetime.now(timezone.utc)
        now_mono = time_module.monotonic()

        # TIER 1: Always compute (cheap SGP4 math)
        iss_lat, iss_lon, iss_alt_km = _compute_iss_position(tle_lines, now_utc)
        speed_kmh = _orbital_speed(iss_alt_km)

        with self._lock:
            # TIER 2: Pass predictions — refresh every 5 minutes or when all cached passes are stale
            all_stale = (self._cached_passes is not None and
                         all(p.get("set_utc", now_utc) <= now_utc for p in self._cached_passes))
            if self._cached_passes is None or all_stale or (now_mono - self._last_pass_fetch_time) >= PASS_REFRESH_INTERVAL:
                n2yo_api_key = device_config.load_env_key("N2YO_SECRET")
                try:
                    new_passes = _predict_passes(tle_lines, lat, lon, now_utc, n2yo_api_key)
                    if new_passes is not None:
                        self._cached_passes = new_passes
                        self._last_pass_fetch_time = now_mono
                        logger.info("Refreshed pass predictions: %d passes", len(new_passes))
                except Exception as e:
                    logger.warning("Pass prediction failed: %s", e)
            # Filter out passes that have already ended
            all_passes = self._cached_passes or []
            passes = [p for p in all_passes if p.get("set_utc", now_utc) > now_utc]

            # TIER 3: Crew count — refresh every 30 minutes (5 min retry on failure)
            crew_interval = CREW_REFRESH_INTERVAL if self._cached_crew_count > 0 else CREW_RETRY_INTERVAL
            if (now_mono - self._last_crew_fetch_time) >= crew_interval:
                count = _get_crew_count()
                self._last_crew_fetch_time = now_mono  # stamp on success AND failure
                if count > 0:
                    self._cached_crew_count = count
            crew_count = self._cached_crew_count

            # TIER 4: Reverse geocode — only when ISS moves significantly
            landmarks = self._get_landmarks()
            if (self._cached_over_text is None or self._over_text_position is None or
                    abs(iss_lat - self._over_text_position[0]) > GEOCODE_MOVE_THRESHOLD or
                    abs(iss_lon - self._over_text_position[1]) > GEOCODE_MOVE_THRESHOLD):
                self._cached_over_text = _reverse_geocode_from_data(iss_lat, iss_lon, landmarks, units)
                self._over_text_position = (iss_lat, iss_lon)
            over_text = self._cached_over_text

            # TIER 5: Ground track — refresh every 30 seconds
            if self._cached_ground_track is None or (now_mono - self._last_track_time) >= TRACK_REFRESH_INTERVAL:
                self._cached_ground_track = _compute_ground_track(tle_lines, now_utc)
                self._last_track_time = now_mono
            ground_track = self._cached_ground_track or []

        mode = _determine_mode(now_utc, passes, prepass_minutes)
        is_passing = mode in ("prepass",) and _is_during_pass(
            now_utc, _get_active_pass(now_utc, passes, prepass_minutes))

        # Pick the "next pass" to surface to the frontend: prefer the next visible pass,
        # otherwise the next overhead pass.
        next_visible = next((p for p in passes if p.get("visible")), None)
        next_any = passes[0] if passes else None
        chosen_pass = next_visible or next_any

        next_pass = None
        if chosen_pass:
            rise_utc = chosen_pass["rise_utc"]
            set_utc = chosen_pass["set_utc"]
            duration_s = (set_utc - rise_utc).total_seconds()
            next_pass = {
                "start_time": rise_utc.isoformat(),
                "end_time": set_utc.isoformat(),
                "max_elevation": round(chosen_pass.get("max_elevation", 0), 1),
                "duration": int(duration_s),
                "visible": bool(chosen_pass.get("visible")),
                "rise_azimuth": round(chosen_pass.get("rise_azimuth", 0), 1),
                "set_azimuth": round(chosen_pass.get("set_azimuth", 0), 1),
            }

        obs_city = settings.get("cityName", "").split(",")[0].strip()
        if not obs_city and weather_city:
            obs_city = weather_city.split(",")[0].strip()
        if not obs_city:
            obs_city = _nearest_city_from_data(lat, lon, landmarks)

        return {
            "iss_position": {
                "lat": round(iss_lat, 4),
                "lng": round(iss_lon, 4),
                "altitude_km": round(iss_alt_km, 1),
                "speed_kmh": round(speed_kmh, 1),
            },
            "ground_track": [{"lat": round(p[0], 4), "lng": round(p[1], 4)} for p in ground_track],
            "next_pass": next_pass,
            "crew_count": crew_count,
            "location_name": over_text,
            "is_passing": bool(is_passing),
            "mode": mode,
            "units": units,
            "observer": {
                "lat": lat,
                "lng": lon,
                "city": obs_city,
            },
            "now_utc": now_utc.isoformat(),
        }


# ═══════════ Helper Functions ═══════════


def _find_weather_location(device_config):
    """Search loop manager for a weather plugin instance with lat/lon configured.

    Returns (lat, lon, city_name) where city_name may be empty.
    """
    try:
        loop_manager = device_config.get_loop_manager()
        for loop in loop_manager.loops:
            for ref in loop.plugin_order:
                if ref.plugin_id == "weather" and ref.plugin_settings:
                    lat = ref.plugin_settings.get("latitude")
                    lon = ref.plugin_settings.get("longitude")
                    if lat is not None and lon is not None:
                        city = ref.plugin_settings.get("customTitle", "")
                        logger.info("ISS Tracker using weather plugin location: %s, %s (%s)", lat, lon, city)
                        return float(lat), float(lon), city
    except Exception as e:
        logger.debug("Could not find weather location: %s", e)
    return 0.0, 0.0, ""


def _parse_float(val, default):
    try:
        if val is None or val == '':
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _load_tle(cache_path):
    """Load TLE data, refreshing from CelesTrak if stale."""
    tle_lines = None
    cache_fresh = False

    # Try loading from cache
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cache = json.load(f)
            cached_time = cache.get("timestamp", 0)
            if time_module.time() - cached_time < TLE_CACHE_MAX_AGE:
                cache_fresh = True
            tle_lines = (cache["line1"], cache["line2"])
        except Exception as e:
            logger.warning("Failed to read TLE cache: %s", e)

    # Fetch fresh TLE if needed
    if not cache_fresh:
        try:
            session = get_http_session()
            response = session.get(TLE_URL, timeout=15)
            response.raise_for_status()
            lines = response.text.strip().splitlines()
            if len(lines) >= 3:
                tle_lines = (lines[1].strip(), lines[2].strip())
            elif len(lines) >= 2:
                tle_lines = (lines[0].strip(), lines[1].strip())

            if tle_lines:
                cache_dir = os.path.dirname(cache_path)
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_path, "w") as f:
                    json.dump(
                        {
                            "line1": tle_lines[0],
                            "line2": tle_lines[1],
                            "timestamp": time_module.time(),
                        },
                        f,
                    )
                logger.info("TLE data refreshed from CelesTrak")
        except Exception as e:
            logger.warning("Failed to fetch TLE from CelesTrak: %s", e)

    if not tle_lines:
        raise RuntimeError("No TLE data available for ISS")

    return tle_lines


def _compute_iss_position(tle_lines, dt_utc):
    """Compute ISS lat/lon/alt using sgp4 directly.

    Tries ``sgp4`` first; if unavailable, falls back to ``skyfield``.
    """
    try:
        from sgp4.api import Satrec, WGS72
    except ImportError:
        return _compute_iss_position_skyfield(tle_lines, dt_utc)

    sat = Satrec.twoline2rv(tle_lines[0], tle_lines[1], WGS72)

    # Convert datetime to Julian date
    jd, fr = _datetime_to_jd(dt_utc)
    e, r, v = sat.sgp4(jd, fr)

    if e != 0:
        raise RuntimeError(f"SGP4 propagation error code: {e}")

    # ECI to lat/lon/alt
    x, y, z = r  # km
    gmst = _gmst(jd, fr)

    # ECEF coordinates
    x_ecef = x * math.cos(gmst) + y * math.sin(gmst)
    y_ecef = -x * math.sin(gmst) + y * math.cos(gmst)
    z_ecef = z

    # Geodetic coordinates
    lon = math.degrees(math.atan2(y_ecef, x_ecef))
    lat = math.degrees(math.atan2(z_ecef, math.sqrt(x_ecef**2 + y_ecef**2)))
    alt = math.sqrt(x**2 + y**2 + z**2) - EARTH_RADIUS_KM

    return lat, lon, alt


def _compute_iss_position_skyfield(tle_lines, dt_utc):
    """Fallback ISS position computation using Skyfield's EarthSatellite."""
    from skyfield.api import load, EarthSatellite

    ts = load.timescale()
    sat = EarthSatellite(tle_lines[0], tle_lines[1], "ISS", ts)
    t = ts.from_datetime(dt_utc)
    geocentric = sat.at(t)
    subpoint = geocentric.subpoint()
    lat = subpoint.latitude.degrees
    lon = subpoint.longitude.degrees
    alt = subpoint.elevation.km
    return lat, lon, alt


def _datetime_to_jd(dt_utc):
    """Convert datetime to Julian date (jd, fraction) pair."""
    y = dt_utc.year
    m = dt_utc.month
    d = dt_utc.day
    if m <= 2:
        y -= 1
        m += 12
    A = int(y / 100)
    B = 2 - A + int(A / 4)
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5

    fr = (
        dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    ) / 24.0 + dt_utc.microsecond / (24.0 * 3600.0 * 1e6)

    return jd, fr


def _gmst(jd, fr):
    """Calculate Greenwich Mean Sidereal Time in radians."""
    T = ((jd - 2451545.0) + fr) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * ((jd - 2451545.0) + fr)
        + 0.000387933 * T**2
        - T**3 / 38710000.0
    )
    return math.radians(gmst_deg % 360)


def _orbital_speed(alt_km):
    """Calculate orbital speed in km/h."""
    mu = 398600.4418  # Earth's gravitational parameter km^3/s^2
    r = EARTH_RADIUS_KM + alt_km
    v = math.sqrt(mu / r)  # km/s
    return v * 3600  # km/h


def _compute_ground_track(tle_lines, now_utc):
    """Compute future ground track points (next ~90 min). Cacheable."""
    if not tle_lines:
        return []
    points = []
    for minutes_ahead in range(0, 95, 2):
        t = now_utc + timedelta(minutes=minutes_ahead)
        try:
            lat, lon, _ = _compute_iss_position(tle_lines, t)
            points.append((lat, lon))
        except Exception:
            break
    return points


def _reverse_geocode_from_data(lat, lon, landmarks, units="metric"):
    """Find nearest landmark using pre-loaded landmarks data."""
    if not landmarks:
        return _ocean_fallback(lat, lon)
    min_dist = float("inf")
    nearest = None
    for lm in landmarks:
        d = _haversine(lat, lon, lm["lat"], lm["lon"])
        if d < min_dist:
            min_dist = d
            nearest = lm
    if nearest and min_dist < 1000:
        if units == "imperial":
            dist_mi = min_dist * 0.621371
            return f"{dist_mi:.0f} mi from {nearest['name']}"
        return f"{min_dist:.0f} km from {nearest['name']}"
    return _ocean_fallback(lat, lon)


def _nearest_city_from_data(lat, lon, landmarks):
    """Find nearest city name from pre-loaded landmarks data."""
    if not landmarks:
        return ""
    min_dist = float("inf")
    nearest = None
    for lm in landmarks:
        d = _haversine(lat, lon, lm["lat"], lm["lon"])
        if d < min_dist:
            min_dist = d
            nearest = lm
    if nearest:
        return nearest["name"].split(",")[0].strip()
    return ""


def _get_crew_count():
    """Get current ISS crew count from Open Notify API."""
    try:
        session = get_http_session()
        response = session.get(CREW_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        return sum(1 for p in data.get("people", []) if p.get("craft") == "ISS")
    except Exception as e:
        logger.warning("Failed to get crew count: %s", e)
        return 0


def _ocean_fallback(lat, lon):
    """Simple ocean basin identification."""
    oceans = [
        ("North Pacific Ocean", 0, 90, 100, 260),
        ("South Pacific Ocean", -90, 0, 140, 290),
        ("North Atlantic Ocean", 0, 90, 280, 360),
        ("North Atlantic Ocean", 0, 90, 0, 10),
        ("South Atlantic Ocean", -90, 0, 290, 360),
        ("South Atlantic Ocean", -90, 0, 0, 20),
        ("Indian Ocean", -90, 30, 20, 140),
        ("Arctic Ocean", 66, 90, 0, 360),
        ("Southern Ocean", -90, -60, 0, 360),
    ]
    for name, lat_min, lat_max, lon_min, lon_max in oceans:
        norm_lon = lon % 360
        if lat_min <= lat <= lat_max and lon_min <= norm_lon <= lon_max:
            return name
    return f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _predict_passes(tle_lines, obs_lat, obs_lon, now_utc, n2yo_api_key=None):
    """Predict visible ISS passes using Skyfield, with N2YO fallback."""
    passes = []

    try:
        passes = _predict_passes_skyfield(tle_lines, obs_lat, obs_lon, now_utc)
    except Exception as e:
        logger.warning("Skyfield pass prediction failed: %s", e)
        if n2yo_api_key:
            try:
                passes = _predict_passes_n2yo(obs_lat, obs_lon, n2yo_api_key)
            except Exception as e2:
                logger.warning("N2YO fallback also failed: %s", e2)

    return passes


def _predict_passes_skyfield(tle_lines, obs_lat, obs_lon, now_utc):
    """Use Skyfield's find_events() for pass prediction with visibility check."""
    from skyfield.api import load, wgs84, EarthSatellite

    ts = load.timescale()
    sat = EarthSatellite(tle_lines[0], tle_lines[1], "ISS", ts)
    observer = wgs84.latlon(obs_lat, obs_lon)

    t0 = ts.from_datetime(now_utc)
    t1 = ts.from_datetime(now_utc + timedelta(days=10))

    t_events, events = sat.find_events(observer, t0, t1, altitude_degrees=10.0)

    # Load ephemeris once for sunlit/sun-altitude checks
    eph = load("de421.bsp")

    passes = []
    current_pass = {}
    culmination_ti = None
    for ti, event in zip(t_events, events):
        dt = ti.utc_datetime()
        if event == 0:  # rise
            current_pass = {"rise_utc": dt}
            culmination_ti = None
            difference = sat - observer
            topocentric = difference.at(ti)
            alt_deg, az_deg, _ = topocentric.altaz()
            current_pass["rise_azimuth"] = az_deg.degrees
        elif event == 1:  # culmination
            if current_pass:
                current_pass["culmination_utc"] = dt
                culmination_ti = ti
                difference = sat - observer
                topocentric = difference.at(ti)
                alt_deg, az_deg, _ = topocentric.altaz()
                current_pass["max_elevation"] = alt_deg.degrees
        elif event == 2:  # set
            if current_pass and "rise_utc" in current_pass:
                current_pass["set_utc"] = dt
                difference = sat - observer
                topocentric = difference.at(ti)
                alt_deg, az_deg, _ = topocentric.altaz()
                current_pass["set_azimuth"] = az_deg.degrees
                current_pass.setdefault("max_elevation", 10)
                current_pass.setdefault("rise_azimuth", 0)

                # Visibility check at culmination (peak of pass)
                visible = False
                if culmination_ti is not None:
                    try:
                        # Check if ISS is sunlit at peak
                        diff_at_peak = (sat - observer).at(culmination_ti)
                        iss_sunlit = diff_at_peak.is_sunlit(eph)

                        # Check if observer is in darkness (sun below -6° = civil twilight)
                        sun = eph["earth"].at(culmination_ti).observe(eph["sun"])
                        # Use observer's position for sun altitude
                        obs_location = eph["earth"] + observer
                        sun_from_obs = obs_location.at(culmination_ti).observe(eph["sun"])
                        sun_alt, _, _ = sun_from_obs.apparent().altaz()
                        observer_dark = sun_alt.degrees < -6.0

                        visible = bool(iss_sunlit) and observer_dark
                    except Exception as e:
                        logger.debug("Visibility check failed for pass: %s", e)

                current_pass["visible"] = visible
                passes.append(current_pass)
                current_pass = {}
                culmination_ti = None

    visible_count = sum(1 for p in passes if p.get("visible"))
    logger.info("Pass prediction: %d total, %d visible", len(passes), visible_count)
    return passes


def _predict_passes_n2yo(obs_lat, obs_lon, api_key):
    """Fallback: use N2YO API for pass prediction."""
    url = (
        f"https://api.n2yo.com/rest/v1/satellite/visualpasses/"
        f"{ISS_CATALOG_NUMBER}/{obs_lat}/{obs_lon}/0/7/10/&apiKey={api_key}"
    )
    session = get_http_session()
    response = session.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    passes = []
    for p in data.get("passes", []):
        rise_utc = datetime.fromtimestamp(p["startUTC"], tz=timezone.utc)
        set_utc = datetime.fromtimestamp(p["endUTC"], tz=timezone.utc)
        passes.append(
            {
                "rise_utc": rise_utc,
                "set_utc": set_utc,
                "max_elevation": p.get("maxEl", 0),
                "rise_azimuth": p.get("startAz", 0),
                "set_azimuth": p.get("endAz", 0),
                "visible": True,  # N2YO visualpasses endpoint only returns visible passes
            }
        )
    return passes


def _determine_mode(now_utc, passes, prepass_minutes):
    """Determine display mode based on visible pass timing."""
    for p in passes:
        if not p.get("visible"):
            continue
        rise = p["rise_utc"]
        sett = p["set_utc"]

        # Post-pass: within 5 minutes after pass ended
        if sett <= now_utc <= sett + timedelta(minutes=POSTPASS_DURATION):
            return "postpass"

        # Pre-pass or during pass
        if rise - timedelta(minutes=prepass_minutes) <= now_utc <= sett:
            return "prepass"

    return "nadir"


def _get_active_pass(now_utc, passes, prepass_minutes):
    """Get the visible pass that is currently active or upcoming within trigger window."""
    for p in passes:
        if not p.get("visible"):
            continue
        rise = p["rise_utc"]
        sett = p["set_utc"]
        if rise - timedelta(minutes=prepass_minutes) <= now_utc <= sett:
            return p
    return None


def _is_during_pass(now_utc, pass_data):
    """Check if currently during a pass (between rise and set)."""
    if not pass_data:
        return False
    return pass_data["rise_utc"] <= now_utc <= pass_data["set_utc"]


def _azimuth_to_compass(az):
    """Convert azimuth degrees to compass direction."""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    ix = round(az / 22.5) % 16
    return dirs[ix]

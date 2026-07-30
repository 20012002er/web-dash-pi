"""Flight tracker plugin — live aircraft positions for the frontend to render on a map.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched aircraft data from ADS-B Exchange-compatible APIs (adsb.fi and
airplanes.live), accumulated position trails, extrapolated positions via dead
reckoning between fetches, detected emergency squawk codes, and rendered
everything on a stitched OpenStreetMap tile composite with PIL. This web
version keeps ALL of that data-fetching, state-management, extrapolation,
and emergency-detection logic intact, but returns the aircraft list and map
bounds as a JSON-serializable dict so the frontend ``dashboard.html``
fragment can render the map with Leaflet.js + OSM tiles.

``get_data`` returns:
    {
        "aircraft": [{hex, flight, lat, lng, altitude, speed, heading,
                       emergency, on_ground, vert_rate, aircraft_type,
                       registration, distance_nm, trail}, ...],
        "map_bounds": {north, south, east, west},
        "center": {lat, lng},
        "radius": float,
        "units": str,
        "observer": {lat, lng},
    }

No resources are bundled — the frontend fetches OSM tiles directly via
Leaflet.js.
"""

import logging
import math
import threading
import time as time_module

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

# API endpoints (both return ADS-B Exchange v2 compatible JSON)
ADSBFI_URL = "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{nm}"
AIRPLANESLIVE_URL = "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}"

# Display limits
MAX_AIRCRAFT_DISPLAY = 30  # Max markers returned to the frontend

# Trail/extrapolation constants
MAX_TRAIL_POINTS = 20  # Max positions per aircraft trail
STALE_GENERATIONS = 2  # Prune after this many missed API fetches
MAX_EXTRAPOLATION_SEC = 120  # Stop extrapolating after 2 min without API data
API_TIMEOUT = 8  # Seconds before giving up on aircraft API

# Emergency squawk codes and their display labels
EMERGENCY_SQUAWKS = {"7500": "HIJACK", "7600": "RADIO", "7700": "EMERG"}

# Earth radius for distance calculations (nautical miles)
EARTH_RADIUS_NM = 3440.065


def _aircraft_id(ac):
    """Return a stable identifier for trail/extrapolation keying."""
    return ac.get("hex") or ac.get("registration") or ac.get("callsign") or None


class FlightTracker(BasePlugin):
    """Tracks nearby aircraft using ADS-B data and returns them for frontend map rendering."""

    def __init__(self, config, **dependencies):
        super().__init__(config, **dependencies)

        self._lock = threading.Lock()

        # Cached API response
        self._cached_aircraft = None
        self._last_fetch_time = 0  # time.monotonic()
        self._last_fetch_params = None  # (lat, lon, radius, source)

        # Trail accumulation: {aircraft_id: {"points": [(lat, lon, mono_time), ...], "last_seen_gen": int}}
        self._trails = {}
        self._fetch_generation = 0

        # Extrapolation base: {aircraft_id: {"lat", "lon", "heading", "speed_kts", "fetch_time"}}
        self._extrapolation_base = {}

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        template_params['hide_refresh_interval'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Fetch aircraft data and return the list + map bounds for the frontend."""
        logger.info("=== Flight Tracker Plugin: Starting ===")

        # Parse location
        lat = _parse_float(settings.get("latitude"), None)
        lon = _parse_float(settings.get("longitude"), None)

        if lat is None or lon is None:
            w_lat, w_lon = _find_weather_location(device_config)
            if lat is None:
                lat = w_lat
            if lon is None:
                lon = w_lon

        if lat is None or lon is None:
            raise RuntimeError("No location configured. Set a location in plugin settings or configure the Weather plugin.")

        # Parse settings (clamp to valid ranges)
        radius_nm = max(1, min(250, _parse_int(settings.get("radius"), 100)))
        units = settings.get("units", "aviation")
        hide_ground = settings.get("hideGround") in ("on", "true", True, "1")
        show_tracks = settings.get("showTracks") not in ("false", False, "0")
        source = settings.get("dataSource", "auto")
        data_interval = _parse_float(settings.get("dataRefreshInterval"), 30)

        # Fetch or reuse cached data
        current_params = (lat, lon, radius_nm, source)
        now = time_module.monotonic()

        with self._lock:
            params_changed = (self._last_fetch_params != current_params)
            time_elapsed = (now - self._last_fetch_time) >= data_interval
            needs_fetch = params_changed or time_elapsed or self._cached_aircraft is None

            if params_changed and self._cached_aircraft is not None:
                # Location/radius changed — clear stale state
                self._trails.clear()
                self._extrapolation_base.clear()
                logger.info("Params changed, cleared trails and extrapolation state")

            if needs_fetch:
                aircraft = _fetch_aircraft(lat, lon, radius_nm, source)
                if aircraft is not None:
                    self._cached_aircraft = aircraft
                    self._last_fetch_time = now
                    self._last_fetch_params = current_params
                    self._fetch_generation += 1
                    self._update_trails(aircraft, now)
                    self._update_extrapolation_base(aircraft, now)
                    logger.info("API fetch: %d aircraft, generation %d", len(aircraft), self._fetch_generation)
                elif self._cached_aircraft is not None:
                    aircraft = self._cached_aircraft
                    logger.warning("API fetch failed, using cached data with extrapolation")
                else:
                    raise RuntimeError("No data available. Could not reach flight tracking API. Check internet connection.")
            else:
                aircraft = self._cached_aircraft
                elapsed = now - self._last_fetch_time
                logger.info("Using cached data (%.1fs old), extrapolating positions", elapsed)

            # Apply dead-reckoning extrapolation
            aircraft = self._extrapolate_positions(aircraft, now, lat, lon)

            # Inject accumulated trails
            aircraft = self._inject_trails(aircraft)

        # Filter and sort (emergency aircraft always first)
        if hide_ground:
            aircraft = [a for a in aircraft if not a.get("on_ground", False)]
        for ac in aircraft:
            ac["_emergency"] = _is_emergency(ac)
        aircraft.sort(key=lambda a: (not a["_emergency"], a.get("distance_nm", 9999)))
        aircraft = aircraft[:MAX_AIRCRAFT_DISPLAY]

        logger.info("Returning %d aircraft within %dnm", len(aircraft), radius_nm)

        # Serialize aircraft for the frontend
        result_aircraft = []
        for ac in aircraft:
            result_aircraft.append({
                "hex": ac.get("hex", ""),
                "flight": (ac.get("callsign") or "").strip(),
                "lat": ac.get("lat"),
                "lng": ac.get("lon"),
                "altitude": ac.get("altitude"),
                "speed": ac.get("speed"),
                "heading": ac.get("heading"),
                "aircraft_type": ac.get("aircraft_type", ""),
                "registration": ac.get("registration", ""),
                "on_ground": bool(ac.get("on_ground", False)),
                "vert_rate": ac.get("vert_rate"),
                "distance_nm": round(ac.get("distance_nm", 0), 1) if ac.get("distance_nm") is not None else None,
                "squawk": ac.get("squawk", ""),
                "emergency": EMERGENCY_SQUAWKS.get(ac.get("squawk", ""), "") if ac.get("_emergency") else "",
                "category": _get_aircraft_category(ac),
                "trail": ac.get("trail") if show_tracks else [],
            })

        # Compute map bounds from the search radius (frontend uses these to fit the view)
        radius_deg = radius_nm / 60.0
        cos_lat = max(math.cos(math.radians(lat)), 0.01)
        bounds = {
            "north": lat + radius_deg,
            "south": lat - radius_deg,
            "east": lon + radius_deg / cos_lat,
            "west": lon - radius_deg / cos_lat,
        }

        logger.info("=== Flight Tracker Plugin: Complete ===")
        return {
            "aircraft": result_aircraft,
            "map_bounds": bounds,
            "center": {"lat": lat, "lng": lon},
            "radius_nm": radius_nm,
            "units": units,
            "observer": {"lat": lat, "lng": lon},
            "show_tracks": show_tracks,
            "aircraft_count": len(result_aircraft),
        }

    # ─────────────────── State Management ───────────────────

    def _update_trails(self, aircraft, fetch_time):
        """Append current API positions to trail history. Called under self._lock."""
        generation = self._fetch_generation

        for ac in aircraft:
            aid = _aircraft_id(ac)
            if not aid:
                continue

            if aid not in self._trails:
                self._trails[aid] = {"points": [], "last_seen_gen": generation}

            entry = self._trails[aid]
            entry["last_seen_gen"] = generation
            entry["points"].append((ac["lat"], ac["lon"], fetch_time))

            if len(entry["points"]) > MAX_TRAIL_POINTS:
                entry["points"] = entry["points"][-MAX_TRAIL_POINTS:]

        # Prune aircraft not seen in recent fetches
        stale_ids = [
            aid for aid, entry in self._trails.items()
            if generation - entry["last_seen_gen"] > STALE_GENERATIONS
        ]
        for aid in stale_ids:
            del self._trails[aid]
            self._extrapolation_base.pop(aid, None)

        if stale_ids:
            logger.info("Pruned %d stale aircraft from trails", len(stale_ids))

    def _update_extrapolation_base(self, aircraft, fetch_time):
        """Snapshot current positions/velocities for dead reckoning. Called under self._lock."""
        for ac in aircraft:
            aid = _aircraft_id(ac)
            if not aid:
                continue
            heading = ac.get("heading")
            speed = ac.get("speed")
            if heading is not None and speed is not None and speed > 0 and not ac.get("on_ground"):
                self._extrapolation_base[aid] = {
                    "lat": ac["lat"],
                    "lon": ac["lon"],
                    "heading": heading,
                    "speed_kts": speed,
                    "fetch_time": fetch_time,
                }
            else:
                self._extrapolation_base.pop(aid, None)

    def _extrapolate_positions(self, aircraft, now, user_lat, user_lon):
        """Apply dead reckoning to shift aircraft positions forward. Called under self._lock."""
        result = []
        for ac in aircraft:
            ac = dict(ac)  # shallow copy to avoid mutating cache
            aid = _aircraft_id(ac)
            base = self._extrapolation_base.get(aid) if aid else None

            if base and base["speed_kts"] > 0:
                elapsed = now - base["fetch_time"]
                if 0 < elapsed < MAX_EXTRAPOLATION_SEC:
                    distance_nm = base["speed_kts"] * (elapsed / 3600.0)
                    heading_rad = math.radians(base["heading"])
                    lat_rad = math.radians(base["lat"])

                    dlat = (distance_nm / 60.0) * math.cos(heading_rad)
                    dlon = (distance_nm / 60.0) * math.sin(heading_rad) / max(math.cos(lat_rad), 0.01)

                    ac["lat"] = base["lat"] + dlat
                    ac["lon"] = base["lon"] + dlon
                    ac["distance_nm"] = _haversine_nm(user_lat, user_lon, ac["lat"], ac["lon"])

            result.append(ac)
        return result

    def _inject_trails(self, aircraft):
        """Replace each aircraft's trail with accumulated trail data plus current position."""
        result = []
        for ac in aircraft:
            ac = dict(ac)
            aid = _aircraft_id(ac)
            trail_points = []
            if aid and aid in self._trails:
                trail_points = [{"lat": p[0], "lon": p[1]} for p in self._trails[aid]["points"]]
            # Append current (possibly extrapolated) position so trail extends to marker
            if ac.get("lat") and ac.get("lon"):
                trail_points.append({"lat": ac["lat"], "lon": ac["lon"]})
            if trail_points:
                ac["trail"] = trail_points
            result.append(ac)
        return result


# ─────────────────── Data Fetching ───────────────────

def _fetch_from_source(session, name, url_template, lat, lon, radius_nm):
    """Fetch and parse aircraft from a single API source. Returns (name, list) or raises."""
    url = url_template.format(lat=lat, lon=lon, nm=radius_nm, radius=radius_nm)
    logger.info("Fetching aircraft from %s: %s", name, url)
    resp = session.get(url, timeout=API_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    aircraft_list = data.get("ac") or []
    result = [p for ac in aircraft_list if (p := _parse_aircraft(ac, lat, lon))]
    logger.info("Got %d aircraft from %s", len(result), name)
    return result


def _fetch_aircraft(lat, lon, radius_nm, source="auto"):
    """Fetch aircraft data from ADS-B API.

    In auto mode, queries both APIs in parallel and returns the first
    successful response.  When a specific source is selected, only that
    API is tried.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    session = get_http_session()

    if source == "adsbfi":
        apis = [("adsb.fi", ADSBFI_URL)]
    elif source == "airplaneslive":
        apis = [("airplanes.live", AIRPLANESLIVE_URL)]
    else:
        apis = [("adsb.fi", ADSBFI_URL), ("airplanes.live", AIRPLANESLIVE_URL)]

    # Single source — simple call
    if len(apis) == 1:
        name, url_template = apis[0]
        try:
            return _fetch_from_source(session, name, url_template, lat, lon, radius_nm)
        except Exception as e:
            logger.warning("Failed to fetch from %s: %s", name, e)
            logger.error("All flight data sources failed")
            return None

    # Auto mode — parallel fetch, take first success
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_fetch_from_source, session, name, tmpl, lat, lon, radius_nm): name
            for name, tmpl in apis
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                return future.result()
            except Exception as e:
                logger.warning("Failed to fetch from %s: %s", name, e)

    logger.error("All flight data sources failed")
    return None


def _parse_aircraft(ac, user_lat, user_lon):
    """Parse a single aircraft record from ADS-B Exchange v2 format."""
    ac_lat = ac.get("lat")
    ac_lon = ac.get("lon")
    if ac_lat is None or ac_lon is None:
        return None

    try:
        ac_lat = float(ac_lat)
        ac_lon = float(ac_lon)
    except (ValueError, TypeError):
        return None

    # Altitude: can be int, float, or "ground"
    alt_baro = ac.get("alt_baro")
    alt_geom = ac.get("alt_geom")
    if alt_baro == "ground":
        altitude = "ground"
        on_ground = True
    elif alt_baro is not None:
        try:
            altitude = int(float(alt_baro))
            on_ground = False
        except (ValueError, TypeError):
            altitude = None
            on_ground = False
    elif alt_geom is not None:
        try:
            altitude = int(float(alt_geom))
            on_ground = False
        except (ValueError, TypeError):
            altitude = None
            on_ground = False
    else:
        altitude = None
        on_ground = bool(ac.get("ground", False))

    callsign = (ac.get("flight") or ac.get("callsign") or "").strip()
    speed_kts = ac.get("gs")  # ground speed in knots
    heading = ac.get("track") or ac.get("true_heading")
    ac_type = ac.get("t", "")  # aircraft type designator
    registration = ac.get("r", "")
    vert_rate = ac.get("baro_rate") or ac.get("geom_rate")  # ft/min
    squawk = ac.get("squawk", "")
    emergency = ac.get("emergency", "none")

    distance_nm = _haversine_nm(user_lat, user_lon, ac_lat, ac_lon)

    return {
        "hex": ac.get("hex", ""),
        "callsign": callsign,
        "lat": ac_lat,
        "lon": ac_lon,
        "altitude": altitude,
        "speed": _parse_float(speed_kts, None),
        "heading": _parse_float(heading, None),
        "aircraft_type": ac_type,
        "registration": registration,
        "on_ground": on_ground,
        "distance_nm": distance_nm,
        "vert_rate": _parse_float(vert_rate, None),
        "squawk": squawk,
        "emergency": emergency != "none" and emergency,
        "trail": [],
    }


# ─────────────────── Aircraft Classification ───────────────────

def _is_helicopter(ac):
    """Return True if aircraft type designator indicates a rotorcraft."""
    ac_type = (ac.get("aircraft_type") or "").upper()
    if not ac_type:
        return False
    # Common helicopter ICAO type prefixes and exact codes
    heli_prefixes = ("H", "EC", "AS", "BO", "BK", "SA", "UH", "AH", "CH", "SH", "MH", "OH", "HH")
    heli_exact = {"R22", "R44", "R66", "S76", "S92", "S61", "B06", "B407", "B412", "B427",
                  "B429", "B430", "B505", "MD11", "MD52", "MD60", "MD90", "MD902"}
    if ac_type in heli_exact:
        return True
    return any(ac_type.startswith(p) for p in heli_prefixes)


def _get_aircraft_category(ac):
    """Classify aircraft into one of: helicopter, airliner, business_jet, ga."""
    if _is_helicopter(ac):
        return "helicopter"
    import re
    ac_type = (ac.get("aircraft_type") or "").upper()
    callsign = (ac.get("callsign") or "").strip()
    is_commercial = bool(re.match(r'^[A-Z]{3}\d', callsign))

    airliner_prefixes = (
        "B71", "B72", "B73", "B74", "B75", "B76", "B77", "B78",  # Boeing
        "A30", "A31", "A32", "A33", "A34", "A35", "A38",           # Airbus
        "MD8", "MD9", "DC8", "DC9", "DC10",                        # MD/DC
        "CRJ", "E17", "E19", "E29", "E190", "E195",                # Regional jets
        "AT4", "AT7", "DH8", "SF34", "B46",                        # Turboprops/regional
        "IL9", "IL6", "TU",                                         # Russian
    )
    if any(ac_type.startswith(p) for p in airliner_prefixes):
        return "airliner"
    bizjet_prefixes = (
        "GL", "LJ",                                      # Gulfstream, Learjet
        "C25", "C55", "C56", "C68", "C75", "C70",       # Citations
        "CL3", "CL60",                                   # Challenger
        "HA4", "HA42",                                   # Hawker
        "F900", "F2TH", "F7X",                           # Falcon
        "PC24",                                          # Pilatus PC-24
        "E50", "E55",                                    # Phenom
        "BE40", "BE400",                                 # Beechjet/400
        "PRM1", "SBR",                                   # Premier, Sabreliner
        "WW24", "GALX",                                  # Westwind, Galaxy
        "G150", "G200", "G280", "G450", "G500",          # Gulfstream numeric
        "G550", "G600", "G650",
        "C680", "C700",                                  # Citation Sovereign/Longitude
        "FA7", "FA50",                                   # Falcon 7X, 50
    )
    if any(ac_type.startswith(p) for p in bizjet_prefixes):
        return "business_jet"
    # Unrecognized type — fall back to callsign heuristic
    if is_commercial:
        return "airliner"
    return "ga"


def _is_emergency(ac):
    """Check if aircraft is squawking an emergency code."""
    if ac.get("emergency"):
        return True
    return ac.get("squawk") in EMERGENCY_SQUAWKS


def _get_aircraft_color(ac):
    """Get marker color based on emergency status or vertical rate (for frontend reference)."""
    if ac.get("_emergency"):
        return "#ff3232"  # Emergency - red
    vert_rate = ac.get("vert_rate")
    if vert_rate is not None:
        if vert_rate > 300:
            return "#64dc64"  # Climbing - green
        elif vert_rate < -300:
            return "#ff8250"  # Descending - orange
    return "#50c8ff"  # Level/default - cyan


# ─────────────────── Coordinate Math ───────────────────

def _haversine_nm(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in nautical miles."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_NM * c


# ─────────────────── Unit Formatting ───────────────────

def _format_altitude(alt_ft, units):
    """Format altitude with units."""
    if units == "metric":
        meters = int(alt_ft * 0.3048)
        if meters >= 10000:
            return f"{meters / 1000:.1f}km"
        return f"{meters:,}m"
    else:
        return f"{alt_ft:,}ft"


def _format_speed(speed_kts, units):
    """Format speed with units."""
    if units == "metric":
        kmh = speed_kts * 1.852
        return f"{kmh:.0f}km/h"
    elif units == "imperial":
        mph = speed_kts * 1.15078
        return f"{mph:.0f}mph"
    else:
        return f"{speed_kts:.0f}kts"


# ─────────────────── Utilities ───────────────────

def _parse_float(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_int(value, default):
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def _find_weather_location(device_config):
    """Try to find location from weather plugin settings."""
    try:
        loop_manager = device_config.get_loop_manager()
        for loop in loop_manager.loops:
            for ref in loop.plugin_order:
                if ref.plugin_id == "weather" and ref.plugin_settings:
                    s = ref.plugin_settings
                    lat = s.get("latitude")
                    lon = s.get("longitude")
                    if lat and lon:
                        return float(lat), float(lon)
                    geo = s.get("geoCoordinates", "")
                    if geo and "," in geo:
                        parts = geo.split(",")
                        return float(parts[0].strip()), float(parts[1].strip())
    except Exception:
        pass
    return None, None

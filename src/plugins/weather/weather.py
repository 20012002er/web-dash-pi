"""Weather plugin — fetches current conditions, hourly, and daily forecasts.

Ported from the original OpenClaw-DashPi project. The original implementation
rendered a multi-panel weather dashboard as a PIL image. This web version keeps
all of the API-fetching logic (OpenWeatherMap One Call v3 + Open-Meteo
fallback, air quality, geocoding, moon phase calculation) and returns the
parsed data as a JSON-serializable dict for the frontend ``dashboard.html``
fragment to render. The PIL rendering helpers and the ``image_loader`` have
been removed accordingly.
"""

import logging
import math
import os
from datetime import datetime, timedelta, timezone, date

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

MOON_PHASE_THRESHOLDS = [
    (1.0, "newmoon"),
    (7.0, "waxingcrescent"),
    (8.5, "firstquarter"),
    (14.0, "waxinggibbous"),
    (15.5, "fullmoon"),
    (22.0, "waninggibbous"),
    (23.5, "lastquarter"),
    (29.0, "waningcrescent"),
]

LUNAR_CYCLE_DAYS = 29.530588853


def get_moon_phase_name(phase_age: float) -> str:
    """Determines the name of the lunar phase based on the age of the moon."""
    for threshold, phase_name in MOON_PHASE_THRESHOLDS:
        if phase_age <= threshold:
            return phase_name
    return "newmoon"


UNITS = {
    "standard": {
        "temperature": "K",
        "speed": "m/s",
        "distance": "km"
    },
    "metric": {
        "temperature": "°C",
        "speed": "m/s",
        "distance": "km"
    },
    "imperial": {
        "temperature": "°F",
        "speed": "mph",
        "distance": "mi"
    }
}

WEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={long}&units={units}&exclude=minutely&appid={api_key}"
AIR_QUALITY_URL = "https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={long}&appid={api_key}"
GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={long}&limit=1&appid={api_key}"

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={long}&hourly=weather_code,temperature_2m,precipitation,precipitation_probability,relative_humidity_2m,surface_pressure,visibility&daily=weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset&current=temperature,windspeed,winddirection,is_day,precipitation,weather_code,apparent_temperature&timezone=auto&models=best_match&forecast_days={forecast_days}"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={long}&hourly=european_aqi,uv_index,uv_index_clear_sky&timezone=auto"
OPEN_METEO_UNIT_PARAMS = {
    "standard": "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",  # temperature is converted to Kelvin later
    "metric":   "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",
    "imperial": "temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
}


class Weather(BasePlugin):
    """Weather dashboard plugin supporting OpenWeatherMap (One Call v3) and Open-Meteo.

    Fetches current conditions (icon, temperature, feels-like, hi/lo, description),
    optional metric data points (sunrise/sunset, wind, humidity, pressure,
    visibility, AQI, UV), an hourly temperature/precipitation forecast, and a
    multi-day forecast row with moon phases.
    """

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "OpenWeatherMap",
            "expected_key": "OPEN_WEATHER_MAP_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Fetch weather data and return it as a JSON-serializable dict.

        Returns a dict with the following shape::

            {
                "current": {
                    "temp", "feels_like", "hi", "lo", "description",
                    "icon_code", "sunrise", "sunset", "wind_speed",
                    "wind_dir", "humidity", "pressure", "visibility",
                    "aqi", "uv"
                },
                "hourly": [{"time", "temp", "precip_prob"}, ...],
                "daily": [{"date", "weather_code", "temp_max", "temp_min",
                           "moon_phase"}, ...],
                "units": {"temperature", "speed", "distance"},
                "location_name": str
            }
        """
        # Validate and convert coordinates with proper error handling
        try:
            lat = float(settings.get('latitude'))
            long = float(settings.get('longitude'))
        except (TypeError, ValueError):
            raise RuntimeError("Latitude and Longitude must be valid numbers.")

        # Check for None/missing (0.0 is a valid coordinate)
        if settings.get('latitude') is None or settings.get('longitude') is None:
            raise RuntimeError("Latitude and Longitude are required.")

        # Validate coordinate ranges
        if not (-90 <= lat <= 90) or not (-180 <= long <= 180):
            raise RuntimeError("Invalid coordinates. Latitude must be -90 to 90, Longitude -180 to 180.")

        units = settings.get('units')
        if not units or units not in ['metric', 'imperial', 'standard']:
            raise RuntimeError("Units are required.")

        weather_provider = settings.get('weatherProvider', 'OpenWeatherMap')
        location_name = settings.get('locationName', '')

        import pytz

        timezone_name = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone_name)

        try:
            if weather_provider == "OpenWeatherMap":
                api_key = device_config.load_env_key("OPEN_WEATHER_MAP_SECRET")
                if not api_key:
                    raise RuntimeError("Open Weather Map API Key not configured.")
                weather_data = self.get_weather_data(api_key, units, lat, long)
                aqi_data = self.get_air_quality(api_key, lat, long)
                if not location_name:
                    location_name = self.get_location(api_key, lat, long)
                if settings.get('weatherTimeZone', 'locationTimeZone') == 'locationTimeZone':
                    logger.info("Using location timezone for OpenWeatherMap data.")
                    wtz = self.parse_timezone(weather_data)
                    parsed = self.parse_weather_data(weather_data, aqi_data, wtz, units, time_format, lat)
                else:
                    logger.info("Using configured timezone for OpenWeatherMap data.")
                    parsed = self.parse_weather_data(weather_data, aqi_data, tz, units, time_format, lat)
            elif weather_provider == "OpenMeteo":
                forecast_days = 7
                weather_data = self.get_open_meteo_data(lat, long, units, forecast_days + 1)
                aqi_data = self.get_open_meteo_air_quality(lat, long)
                parsed = self.parse_open_meteo_data(weather_data, aqi_data, tz, units, time_format, lat)
            else:
                raise RuntimeError(f"Unknown weather provider: {weather_provider}")
        except Exception as e:
            logger.error(f"{weather_provider} request failed: {str(e)}")
            raise RuntimeError(f"{weather_provider} request failure, please check logs.")

        # Add last refresh time
        now = datetime.now(tz)
        if time_format == "24h":
            last_refresh_time = now.strftime("%Y-%m-%d %H:%M")
        else:
            last_refresh_time = now.strftime("%Y-%m-%d %I:%M %p")
        parsed["last_refresh_time"] = last_refresh_time
        parsed["location_name"] = location_name

        return self._to_response(parsed, units)

    # ------------------------------------------------------------------
    # Response shaping
    # ------------------------------------------------------------------
    def _to_response(self, parsed, units):
        """Map the internal parsed dict to the documented get_data() response."""
        current = parsed.get("current", {}) if isinstance(parsed.get("current"), dict) else {}
        # The internal parse functions store flat current-conditions fields at
        # the top level of ``parsed``; gather them into a nested ``current``
        # dict for the frontend.
        forecast = parsed.get("forecast", [])
        hourly = parsed.get("hourly_forecast", [])
        data_points = parsed.get("data_points", [])

        def _dp(label):
            for dp in data_points:
                if dp.get("label") == label:
                    return dp
            return {}

        sunrise_dp = _dp("Sunrise")
        sunset_dp = _dp("Sunset")
        wind_dp = _dp("Wind")
        humidity_dp = _dp("Humidity")

        # Extract icon code from the stored icon path (e.g. ".../icons/01d.png")
        def _icon_code_from_path(path):
            if not path:
                return "01d"
            base = os.path.basename(path)
            stem, _ = os.path.splitext(base)
            return stem

        current_icon_code = _icon_code_from_path(parsed.get("current_day_icon"))
        forecast_list = parsed.get("forecast", [])

        hi = forecast_list[0]["high"] if forecast_list else None
        lo = forecast_list[0]["low"] if forecast_list else None

        current_section = {
            "temp": parsed.get("current_temperature"),
            "feels_like": parsed.get("feels_like"),
            "hi": hi,
            "lo": lo,
            "description": parsed.get("weather_description", ""),
            "icon_code": current_icon_code,
            "sunrise": sunrise_dp.get("measurement", ""),
            "sunset": sunset_dp.get("measurement", ""),
            "wind_speed": wind_dp.get("measurement"),
            "wind_dir": wind_dp.get("arrow", ""),
            "humidity": humidity_dp.get("measurement"),
            "pressure": None,
            "visibility": None,
            "aqi": None,
            "uv": None,
        }

        # AQI / UV are exposed in the OpenWeatherMap air quality response and
        # the Open-Meteo air quality response; surface them if present.
        aqi_value = parsed.get("aqi")
        if aqi_value is not None:
            current_section["aqi"] = aqi_value
        uv_value = parsed.get("uv")
        if uv_value is not None:
            current_section["uv"] = uv_value

        hourly_out = []
        for hr in hourly[:24]:
            hourly_out.append({
                "time": hr.get("time", ""),
                "temp": hr.get("temperature"),
                "precip_prob": hr.get("precipitation"),
            })

        daily_out = []
        for day in forecast_list:
            daily_out.append({
                "date": day.get("day", ""),
                "weather_code": _icon_code_from_path(day.get("icon", "")),
                "temp_max": day.get("high"),
                "temp_min": day.get("low"),
                "moon_phase": _icon_code_from_path(day.get("moon_phase_icon", "")),
                "moon_phase_pct": day.get("moon_phase_pct", ""),
            })

        return {
            "current": current_section,
            "hourly": hourly_out,
            "daily": daily_out,
            "units": {
                "temperature": UNITS[units]["temperature"],
                "speed": UNITS[units]["speed"],
                "distance": UNITS[units]["distance"],
            },
            "location_name": parsed.get("location_name", ""),
            "last_refresh_time": parsed.get("last_refresh_time", ""),
            "current_date": parsed.get("current_date", ""),
        }

    # ------------------------------------------------------------------
    # OpenWeatherMap parsing
    # ------------------------------------------------------------------
    def parse_weather_data(self, weather_data, aqi_data, tz, units, time_format, lat):
        """Parse OpenWeatherMap One Call v3 response into a normalized template dict."""
        current = weather_data.get("current")
        daily_forecast = weather_data.get("daily", [])
        dt = datetime.fromtimestamp(current.get('dt'), tz=timezone.utc).astimezone(tz)
        weather_list = current.get("weather", [])
        if not weather_list:
            raise RuntimeError("Weather data missing from API response.")
        current_icon = weather_list[0].get("icon", "01d")
        icon_codes_to_preserve = ["01", "02", "10"]
        icon_code = current_icon[:2]
        current_suffix = current_icon[-1]

        if icon_code not in icon_codes_to_preserve:
            if current_icon.endswith('n'):
                current_icon = current_icon.replace("n", "d")
        weather_description = weather_list[0].get("description", "").title()

        data = {
            "current_date": dt.strftime("%A, %B %d"),
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_temperature": str(round(current["temp"])) if current.get("temp") is not None else "--",
            "feels_like": str(round(current["feels_like"])) if current.get("feels_like") is not None else "--",
            "weather_description": weather_description,
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        }
        data['forecast'] = self.parse_forecast(weather_data.get('daily') or [], tz, current_suffix, lat)
        data['data_points'] = self.parse_data_points(weather_data, aqi_data, tz, units, time_format)

        data['hourly_forecast'] = self.parse_hourly(weather_data.get('hourly') or [], tz, time_format, units, daily_forecast)

        # Surface AQI and UV from the air quality response, if available.
        try:
            aqi_list = aqi_data.get("list") if aqi_data else None
            if aqi_list:
                aqi_value = aqi_list[0].get("main", {}).get("aqi")
                if aqi_value is not None:
                    data["aqi"] = aqi_value
        except Exception as e:
            logger.debug(f"Could not extract AQI: {e}")

        alerts_raw = weather_data.get("alerts", [])
        parsed_alerts = []
        for a in alerts_raw:
            if not a.get("event"):
                continue
            alert = {"event": a.get("event", ""), "sender": a.get("sender_name", "")}
            end_ts = a.get("end")
            if end_ts:
                try:
                    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc).astimezone(tz)
                    alert["until_str"] = self.format_time(end_dt, time_format)
                except Exception:
                    pass
            parsed_alerts.append(alert)
        data['alerts'] = parsed_alerts
        return data

    def parse_open_meteo_data(self, weather_data, aqi_data, tz, units, time_format, lat):
        """Parse Open-Meteo API response into the same normalized template dict as parse_weather_data()."""
        current = weather_data.get("current", {})
        daily = weather_data.get('daily', {})
        dt = datetime.fromisoformat(current.get('time')).astimezone(tz) if current.get('time') else datetime.now(tz)
        weather_code = current.get("weather_code", 0)
        is_day = current.get("is_day", 1)
        current_icon = self.map_weather_code_to_icon(weather_code, is_day)

        temperature_conversion = 273.15 if units == "standard" else 0.

        weather_description = self.get_weather_description(weather_code)

        data = {
            "current_date": dt.strftime("%A, %B %d"),
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_temperature": str(round(current.get("temperature", 0) + temperature_conversion)),
            "feels_like": str(round(current.get("apparent_temperature", current.get("temperature", 0)) + temperature_conversion)),
            "weather_description": weather_description,
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        }

        data['forecast'] = self.parse_open_meteo_forecast(weather_data.get('daily', {}), units, tz, is_day, lat)
        data['data_points'] = self.parse_open_meteo_data_points(weather_data, aqi_data, units, tz, time_format)

        data['hourly_forecast'] = self.parse_open_meteo_hourly(weather_data.get('hourly', {}), units, tz, time_format, daily.get('sunrise', []), daily.get('sunset', []))

        # Surface AQI and UV from the Open-Meteo air quality response, if present.
        try:
            if aqi_data:
                hourly_aqi = aqi_data.get("hourly", {})
                eu_aqi = hourly_aqi.get("european_aqi", [])
                uv_index = hourly_aqi.get("uv_index", [])
                if eu_aqi:
                    data["aqi"] = eu_aqi[0]
                if uv_index:
                    data["uv"] = uv_index[0]
        except Exception as e:
            logger.debug(f"Could not extract Open-Meteo AQI/UV: {e}")

        data['alerts'] = []  # Open-Meteo does not provide weather alerts
        return data

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------
    def map_weather_code_to_icon(self, weather_code, is_day):
        """Map an Open-Meteo WMO weather code to a local icon filename."""
        icon = "01d"  # Default to clear day icon

        if weather_code in [0]:
            icon = "01d"
        elif weather_code in [1]:
            icon = "022d"
        elif weather_code in [2]:
            icon = "02d"
        elif weather_code in [3]:
            icon = "04d"
        elif weather_code in [51, 61, 80]:
            icon = "51d"
        elif weather_code in [53, 63, 81]:
            icon = "53d"
        elif weather_code in [55, 65, 82]:
            icon = "09d"
        elif weather_code in [45]:
            icon = "50d"
        elif weather_code in [48]:
            icon = "48d"
        elif weather_code in [56, 66]:
            icon = "56d"
        elif weather_code in [57, 67]:
            icon = "57d"
        elif weather_code in [71, 85]:
            icon = "71d"
        elif weather_code in [73]:
            icon = "73d"
        elif weather_code in [75, 86]:
            icon = "13d"
        elif weather_code in [77]:
            icon = "77d"
        elif weather_code in [95]:
            icon = "11d"
        elif weather_code in [96, 99]:
            icon = "11d"

        if is_day == 0:
            if icon == "01d":
                icon = "01n"
            elif icon == "022d":
                icon = "022n"
            elif icon == "02d":
                icon = "02n"
            elif icon == "10d":
                icon = "10n"

        return icon

    def get_weather_description(self, weather_code):
        """Map Open-Meteo weather code to human-readable description."""
        descriptions = {
            0: "Clear Sky",
            1: "Mainly Clear",
            2: "Partly Cloudy",
            3: "Overcast",
            45: "Foggy",
            48: "Icy Fog",
            51: "Light Drizzle",
            53: "Moderate Drizzle",
            55: "Heavy Drizzle",
            56: "Light Freezing Drizzle",
            57: "Freezing Drizzle",
            61: "Light Rain",
            63: "Moderate Rain",
            65: "Heavy Rain",
            66: "Light Freezing Rain",
            67: "Freezing Rain",
            71: "Light Snow",
            73: "Moderate Snow",
            75: "Heavy Snow",
            77: "Snow Grains",
            80: "Light Showers",
            81: "Moderate Showers",
            82: "Heavy Showers",
            85: "Light Snow Showers",
            86: "Heavy Snow Showers",
            95: "Thunderstorm",
            96: "Thunderstorm with Light Hail",
            99: "Thunderstorm with Heavy Hail"
        }
        return descriptions.get(weather_code, "Unknown")

    def get_moon_phase_icon_path(self, phase_name: str, lat: float) -> str:
        """Determines the path to the moon icon, inverting it if the location is in the Southern Hemisphere."""
        if lat < 0:  # Southern Hemisphere
            if phase_name == "waxingcrescent":
                phase_name = "waningcrescent"
            elif phase_name == "waxinggibbous":
                phase_name = "waninggibbous"
            elif phase_name == "waningcrescent":
                phase_name = "waxingcrescent"
            elif phase_name == "waninggibbous":
                phase_name = "waxinggibbous"
            elif phase_name == "firstquarter":
                phase_name = "lastquarter"
            elif phase_name == "lastquarter":
                phase_name = "firstquarter"

        return self.get_plugin_dir(f"icons/{phase_name}.png")

    def parse_forecast(self, daily_forecast, tz, current_suffix, lat):
        """Parse the daily forecast from OpenWeatherMap One Call v3."""
        PHASES = [
            (0.0, "newmoon"),
            (0.25, "firstquarter"),
            (0.5, "fullmoon"),
            (0.75, "lastquarter"),
            (1.0, "newmoon"),
        ]

        def choose_phase_name(phase: float) -> str:
            for target, name in PHASES:
                if math.isclose(phase, target, abs_tol=1e-3):
                    return name
            if 0.0 < phase < 0.25:
                return "waxingcrescent"
            elif 0.25 < phase < 0.5:
                return "waxinggibbous"
            elif 0.5 < phase < 0.75:
                return "waninggibbous"
            else:
                return "waningcrescent"

        forecast = []
        icon_codes_to_apply_current_suffix = ["01", "02", "10"]
        for day in daily_forecast:
            try:
                weather_icon = day["weather"][0]["icon"]  # e.g. "10d", "01n"
                icon_code = weather_icon[:2]
                if icon_code in icon_codes_to_apply_current_suffix:
                    weather_icon_base = weather_icon[:-1]
                    weather_icon = weather_icon_base + current_suffix
                else:
                    if weather_icon.endswith('n'):
                        weather_icon = weather_icon.replace("n", "d")
                weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

                moon_phase = float(day["moon_phase"])  # [0.0–1.0]
                phase_name_north_hemi = choose_phase_name(moon_phase)
                moon_icon_path = self.get_moon_phase_icon_path(phase_name_north_hemi, lat)
                illum_fraction = (1 - math.cos(2 * math.pi * moon_phase)) / 2
                moon_pct = f"{illum_fraction * 100:.0f}"

                dt = datetime.fromtimestamp(day["dt"], tz=timezone.utc).astimezone(tz)
                day_label = dt.strftime("%a")

                forecast.append(
                    {
                        "day": day_label,
                        "high": int(day["temp"]["max"]),
                        "low": int(day["temp"]["min"]),
                        "icon": weather_icon_path,
                        "moon_phase_pct": moon_pct,
                        "moon_phase_icon": moon_icon_path,
                    }
                )
            except (KeyError, IndexError, TypeError) as e:
                logger.warning(f"Skipping malformed forecast day: {e}")
                continue

        return forecast

    def parse_open_meteo_forecast(self, daily_data, units, tz, is_day, lat):
        """Parse the daily forecast from Open-Meteo API and calculate moon phase and illumination."""
        times = daily_data.get('time', [])
        weather_codes = daily_data.get('weathercode', [])
        temp_max = daily_data.get('temperature_2m_max', [])
        temp_min = daily_data.get('temperature_2m_min', [])
        if units == "standard":
            temp_max = [T + 273.15 for T in temp_max]
            temp_min = [T + 273.15 for T in temp_min]

        forecast = []

        try:
            from astral import moon as astral_moon
        except ImportError:
            astral_moon = None

        for i in range(len(times)):
            dt = datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc).astimezone(tz)
            day_label = dt.strftime("%a")

            code = weather_codes[i] if i < len(weather_codes) else 0
            weather_icon = self.map_weather_code_to_icon(code, is_day=1)
            weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            target_date: date = dt.date() + timedelta(days=1)

            try:
                phase_age = astral_moon.phase(target_date) if astral_moon else 0
                phase_name_north_hemi = get_moon_phase_name(phase_age)
                phase_fraction = phase_age / LUNAR_CYCLE_DAYS
                illum_pct = (1 - math.cos(2 * math.pi * phase_fraction)) / 2 * 100
            except Exception as e:
                logger.error(f"Error calculating moon phase for {target_date}: {e}")
                illum_pct = 0
                phase_name_north_hemi = "newmoon"
            moon_icon_path = self.get_moon_phase_icon_path(phase_name_north_hemi, lat)

            forecast.append({
                "day": day_label,
                "high": int(temp_max[i]) if i < len(temp_max) else 0,
                "low": int(temp_min[i]) if i < len(temp_min) else 0,
                "icon": weather_icon_path,
                "moon_phase_pct": f"{illum_pct:.0f}",
                "moon_phase_icon": moon_icon_path
            })

        return forecast

    def parse_hourly(self, hourly_forecast, tz, time_format, units, daily_forecast):
        hourly = []
        icon_codes_to_preserve = ["01", "02", "10"]

        sun_map = {}
        for day in daily_forecast:
            day_date = datetime.fromtimestamp(day['dt'], tz=timezone.utc).astimezone(tz).date()
            sun_map[day_date] = (day['sunrise'], day['sunset'])

        for hour in hourly_forecast[:24]:
            dt_epoch = hour.get('dt')
            dt = datetime.fromtimestamp(dt_epoch, tz=timezone.utc).astimezone(tz)
            rain_mm = hour.get("rain", {}).get("1h", 0.0)
            snow_mm = hour.get("snow", {}).get("1h", 0.0)
            total_precip_mm = rain_mm + snow_mm
            sunrise, sunset = sun_map.get(dt.date(), (0, 0))

            is_day = sunrise <= dt_epoch < sunset
            suffix = 'd' if is_day else 'n'

            raw_icon = hour.get("weather", [{}])[0].get("icon", "01d")
            icon_base = raw_icon[:2]
            icon_name = f"{icon_base}{suffix}" if icon_base in icon_codes_to_preserve else f"{icon_base}d"

            if units == "imperial":
                precip_value = total_precip_mm / 25.4
            else:
                precip_value = total_precip_mm
            hour_forecast = {
                "time": self.format_time(dt, time_format, hour_only=True),
                "temperature": int(hour["temp"]) if hour.get("temp") is not None else 0,
                "precipitation": hour.get("pop"),
                "rain": round(precip_value, 2),
                "icon": self.get_plugin_dir(f'icons/{icon_name}.png')
            }
            hourly.append(hour_forecast)
        return hourly

    def parse_open_meteo_hourly(self, hourly_data, units, tz, time_format, sunrises, sunsets):
        hourly = []
        times = hourly_data.get('time', [])
        temperatures = hourly_data.get('temperature_2m', [])
        if units == "standard":
            temperatures = [temperature + 273.15 for temperature in temperatures]
        precipitation_probabilities = hourly_data.get('precipitation_probability', [])
        rain = hourly_data.get('precipitation', [])
        codes = hourly_data.get('weather_code', [])

        sun_map = {}
        for sr_s, ss_s in zip(sunrises, sunsets):
            sr_dt = datetime.fromisoformat(sr_s).astimezone(tz)
            ss_dt = datetime.fromisoformat(ss_s).astimezone(tz)
            sun_map[sr_dt.date()] = (sr_dt, ss_dt)

        current_time_in_tz = datetime.now(tz)
        start_index = 0
        for i, time_str in enumerate(times):
            try:
                dt_hourly = datetime.fromisoformat(time_str).astimezone(tz)
                if dt_hourly.date() == current_time_in_tz.date() and dt_hourly.hour >= current_time_in_tz.hour:
                    start_index = i
                    break
                if dt_hourly.date() > current_time_in_tz.date():
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} in hourly data.")
                continue

        sliced_times = times[start_index:]
        sliced_temperatures = temperatures[start_index:]
        sliced_precipitation_probabilities = precipitation_probabilities[start_index:]
        sliced_rain = rain[start_index:]
        sliced_codes = codes[start_index:]

        for i in range(min(24, len(sliced_times))):
            dt = datetime.fromisoformat(sliced_times[i]).astimezone(tz)
            sunrise, sunset = sun_map.get(dt.date(), (None, None))
            is_day = 0
            if sunrise and sunset:
                is_day = 1 if sunrise <= dt < sunset else 0
            code = sliced_codes[i] if i < len(sliced_codes) else 0
            icon_name = self.map_weather_code_to_icon(code, is_day)
            hour_forecast = {
                "time": self.format_time(dt, time_format, True),
                "temperature": int(sliced_temperatures[i]) if i < len(sliced_temperatures) else 0,
                "precipitation": (sliced_precipitation_probabilities[i] / 100) if i < len(sliced_precipitation_probabilities) else 0,
                "rain": (sliced_rain[i]) if i < len(sliced_rain) else 0,
                "icon": self.get_plugin_dir(f"icons/{icon_name}.png")
            }
            hourly.append(hour_forecast)
        return hourly

    def parse_data_points(self, weather, air_quality, tz, units, time_format):
        """Extract current metric data points (sunrise, sunset, wind, humidity) from OWM data."""
        data_points = []
        sunrise_epoch = weather.get('current', {}).get("sunrise")

        if sunrise_epoch:
            sunrise_dt = datetime.fromtimestamp(sunrise_epoch, tz=timezone.utc).astimezone(tz)
            data_points.append({
                "label": "Sunrise",
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logger.info("Sunrise not found — expected for polar areas in midnight sun / polar night periods.")

        sunset_epoch = weather.get('current', {}).get("sunset")
        if sunset_epoch:
            sunset_dt = datetime.fromtimestamp(sunset_epoch, tz=timezone.utc).astimezone(tz)
            data_points.append({
                "label": "Sunset",
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logger.info("Sunset not found — expected for polar areas in midnight sun / polar night periods.")

        wind_deg = weather.get('current', {}).get("wind_deg", 0)
        wind_arrow = self.get_wind_arrow(wind_deg)
        data_points.append({
            "label": "Wind",
            "measurement": weather.get('current', {}).get("wind_speed"),
            "unit": UNITS[units]["speed"],
            "icon": self.get_plugin_dir('icons/wind.png'),
            "arrow": wind_arrow
        })

        data_points.append({
            "label": "Humidity",
            "measurement": weather.get('current', {}).get("humidity"),
            "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        return data_points

    def parse_open_meteo_data_points(self, weather_data, aqi_data, units, tz, time_format):
        """Parses current data points from Open-Meteo API response."""
        data_points = []
        daily_data = weather_data.get('daily', {})
        current_data = weather_data.get('current', {})
        hourly_data = weather_data.get('hourly', {})

        current_time = datetime.now(tz)

        # Sunrise
        sunrise_times = daily_data.get('sunrise', [])
        if sunrise_times:
            sunrise_dt = datetime.fromisoformat(sunrise_times[0]).astimezone(tz)
            data_points.append({
                "label": "Sunrise",
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logger.info("Sunrise not found — expected for polar areas in midnight sun / polar night periods.")

        # Sunset
        sunset_times = daily_data.get('sunset', [])
        if sunset_times:
            sunset_dt = datetime.fromisoformat(sunset_times[0]).astimezone(tz)
            data_points.append({
                "label": "Sunset",
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logger.info("Sunset not found — expected for polar areas in midnight sun / polar night periods.")

        # Wind
        wind_speed = current_data.get("windspeed", 0)
        wind_deg = current_data.get("winddirection", 0)
        wind_arrow = self.get_wind_arrow(wind_deg)
        wind_unit = UNITS[units]["speed"]
        data_points.append({
            "label": "Wind", "measurement": wind_speed, "unit": wind_unit,
            "icon": self.get_plugin_dir('icons/wind.png'), "arrow": wind_arrow
        })

        # Humidity
        current_humidity = "N/A"
        humidity_hourly_times = hourly_data.get('time', [])
        humidity_values = hourly_data.get('relative_humidity_2m', [])
        for i, time_str in enumerate(humidity_hourly_times):
            try:
                if datetime.fromisoformat(time_str).astimezone(tz).hour == current_time.hour:
                    if i < len(humidity_values):
                        current_humidity = int(humidity_values[i])
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for humidity.")
                continue
        data_points.append({
            "label": "Humidity", "measurement": current_humidity, "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        return data_points

    def get_wind_arrow(self, wind_deg: float) -> str:
        """Convert wind direction in degrees to a Unicode arrow character."""
        DIRECTIONS = [
            ("↓", 22.5),    # North (N)
            ("↙", 67.5),    # North-East (NE)
            ("←", 112.5),   # East (E)
            ("↖", 157.5),   # South-East (SE)
            ("↑", 202.5),   # South (S)
            ("↗", 247.5),   # South-West (SW)
            ("→", 292.5),   # West (W)
            ("↘", 337.5),   # North-West (NW)
            ("↓", 360.0)    # Wrap back to North
        ]
        wind_deg = wind_deg % 360
        for arrow, upper_bound in DIRECTIONS:
            if wind_deg < upper_bound:
                return arrow

        return "↑"

    # ------------------------------------------------------------------
    # HTTP fetchers
    # ------------------------------------------------------------------
    def get_weather_data(self, api_key, units, lat, long):
        url = WEATHER_URL.format(lat=lat, long=long, units=units, api_key=api_key)
        session = get_http_session()
        response = session.get(url, timeout=30)
        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve weather data: status={response.status_code}")
            raise RuntimeError("Failed to retrieve weather data.")

        return response.json()

    def get_air_quality(self, api_key, lat, long):
        url = AIR_QUALITY_URL.format(lat=lat, long=long, api_key=api_key)
        session = get_http_session()
        response = session.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to get air quality data: status={response.status_code}")
            raise RuntimeError("Failed to retrieve air quality data.")

        return response.json()

    def get_location(self, api_key, lat, long):
        url = GEOCODING_URL.format(lat=lat, long=long, api_key=api_key)
        session = get_http_session()
        response = session.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to get location: status={response.status_code}")
            raise RuntimeError("Failed to retrieve location.")

        location_list = response.json()
        if not location_list:
            logger.warning("Geocoding returned empty results, using coordinates as location")
            return f"{lat}, {long}"
        location_data = location_list[0]
        location_str = f"{location_data.get('name')}, {location_data.get('state', location_data.get('country'))}"

        return location_str

    def get_open_meteo_data(self, lat, long, units, forecast_days):
        unit_params = OPEN_METEO_UNIT_PARAMS[units]
        url = OPEN_METEO_FORECAST_URL.format(lat=lat, long=long, forecast_days=forecast_days) + f"&{unit_params}"
        session = get_http_session()
        response = session.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo weather data: status={response.status_code}")
            raise RuntimeError("Failed to retrieve Open-Meteo weather data.")

        return response.json()

    def get_open_meteo_air_quality(self, lat, long):
        url = OPEN_METEO_AIR_QUALITY_URL.format(lat=lat, long=long)
        session = get_http_session()
        response = session.get(url, timeout=30)
        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo air quality data: status={response.status_code}")
            raise RuntimeError("Failed to retrieve Open-Meteo air quality data.")

        return response.json()

    def format_time(self, dt, time_format, hour_only=False, include_am_pm=True):
        """Format datetime based on 12h or 24h preference"""
        if time_format == "24h":
            return dt.strftime("%H:00" if hour_only else "%H:%M")

        if include_am_pm:
            fmt = "%I %p" if hour_only else "%I:%M %p"
        else:
            fmt = "%I" if hour_only else "%I:%M"

        return dt.strftime(fmt).lstrip("0")

    def parse_timezone(self, weatherdata):
        """Parse timezone from weather data"""
        import pytz

        if 'timezone' in weatherdata:
            logger.info(f"Using timezone from weather data: {weatherdata['timezone']}")
            return pytz.timezone(weatherdata['timezone'])
        else:
            logger.error("Failed to retrieve Timezone from weather data")
            raise RuntimeError("Timezone not found in weather data.")

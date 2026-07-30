"""Calendar plugin — fetches iCal events and returns them for frontend rendering.

Ported from the original OpenClaw-DashPi project. The original implementation
fetched one or more iCal URLs, expanded recurring events with
``recurring-ical-events``, and rendered day/week/month/list views as a PIL
image. This web version keeps the fetching, expansion, and view-range logic
intact but returns a JSON-serializable dict (events + view metadata) so the
frontend ``dashboard.html`` fragment can render the selected view with CSS
grid/flexbox.

``get_data`` returns:
    {
        "events": [{title, start, end, all_day, color, text_color, calendar_idx}, ...],
        "view_mode": str,
        "title": str,
        "display_weekends": bool,
        "week_start_day": int,
        "background_color": str,
        "text_color": str,
        "time_format": str,
        "now_iso": str,
        "start_hour": int,
        "end_hour": int,
        "display_now_indicator": bool,
        "now_indicator_color": str,
    }
"""

import calendar as cal_mod
import logging
from datetime import datetime, timedelta

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.calendar.constants import LOCALE_MAP
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)


class Calendar(BasePlugin):
    """Fetches iCal events and returns them for the frontend to render in a calendar view."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        template_params['locale_map'] = LOCALE_MAP
        return template_params

    def get_data(self, settings, device_config):
        """Fetch calendar events for the configured view range and return them as a dict."""
        import pytz

        calendar_urls = settings.get('calendarURLs[]')
        calendar_colors = settings.get('calendarColors[]')
        view = settings.get("viewMode")

        if not view:
            raise RuntimeError("View is required")
        elif view not in ["timeGridDay", "timeGridWeek", "dayGrid", "dayGridMonth", "listMonth"]:
            raise RuntimeError("Invalid view")

        # Filter out empty URLs (form may include blank entries from placeholder inputs)
        raw_urls = list(calendar_urls) if calendar_urls else []
        if calendar_urls:
            calendar_urls = [url for url in calendar_urls if url and url.strip()]
            if calendar_colors and len(calendar_colors) > len(raw_urls):
                # Keep colors aligned with non-empty URLs
                calendar_colors = [c for url, c in zip(raw_urls, calendar_colors) if url and url.strip()]
        if not calendar_urls:
            raise RuntimeError("At least one calendar URL is required")

        # Ensure colors list matches URLs (default blue if missing)
        if not calendar_colors or len(calendar_colors) < len(calendar_urls):
            default_color = "#3788d8"
            calendar_colors = (list(calendar_colors) if calendar_colors else []) + \
                [default_color] * (len(calendar_urls) - (len(calendar_colors) if calendar_colors else 0))

        timezone_name = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        try:
            tz = pytz.timezone(timezone_name)
        except Exception as e:
            logger.warning("Invalid timezone '%s', falling back to UTC: %s", timezone_name, e)
            tz = pytz.utc

        current_dt = datetime.now(tz)
        start, end = self.get_view_range(view, current_dt, settings)
        logger.debug("Fetching events for %s --> [%s] --> %s", start, current_dt, end)
        events = self.fetch_ics_events(calendar_urls, calendar_colors, tz, start, end)
        if not events:
            logger.warning("No events found for ics url")

        # Normalize the week view: the original code collapsed timeGridWeek into a
        # generic 'timeGrid' view when previous days should NOT be displayed.
        effective_view = view
        if view == 'timeGridWeek' and settings.get("displayPreviousDays") != "true":
            effective_view = 'timeGrid'

        show_title = settings.get("displayTitle") == "true"
        title = ""
        if show_title:
            if effective_view == "timeGridDay":
                title = current_dt.strftime("%A, %B %d, %Y")
            elif effective_view in ("timeGridWeek", "timeGrid"):
                title = current_dt.strftime("%B %Y")
            elif effective_view in ("dayGridMonth", "dayGrid"):
                title = current_dt.strftime("%B %Y")
            elif effective_view == "listMonth":
                title = current_dt.strftime("%B %Y")

        try:
            return {
                "events": events,
                "view_mode": effective_view,
                "title": title,
                "display_weekends": settings.get("displayWeekends", "true") == "true",
                "week_start_day": int(settings.get("weekStartDay", 0)),
                "background_color": settings.get("backgroundColor", "#ffffff"),
                "text_color": settings.get("textColor", "#000000"),
                "time_format": time_format,
                "now_iso": current_dt.isoformat(),
                "start_hour": int(settings.get("startTimeInterval", 0) or 0),
                "end_hour": int(settings.get("endTimeInterval", 24) or 24),
                "display_now_indicator": settings.get("displayNowIndicator", "true") == "true",
                "now_indicator_color": settings.get("nowIndicatorColor", "#ff0000"),
                "display_event_time": settings.get("displayEventTime", "true") == "true",
                # Extra metadata for the frontend's week/time-grid layout
                "today": current_dt.date().isoformat(),
                "view_start_iso": start.isoformat(),
                "view_end_iso": end.isoformat(),
            }
        except Exception as e:
            logger.error("Failed to build calendar data: %s", e)
            raise RuntimeError("Failed to display calendar.")

    def fetch_ics_events(self, calendar_urls, colors, tz, start_range, end_range):
        """Fetch and expand events from all iCal URLs within the given time range."""
        import recurring_ical_events

        parsed_events = []

        for cal_idx, (calendar_url, color) in enumerate(zip(calendar_urls, colors)):
            try:
                ical = self.fetch_calendar(calendar_url)
                events = recurring_ical_events.of(ical).between(start_range, end_range)
                contrast_color = self.get_contrast_color(color)

                for event in events:
                    start, end, all_day = self.parse_data_points(event, tz)
                    parsed_event = {
                        "title": str(event.get("summary")),
                        "start": start,
                        "color": color,
                        "text_color": contrast_color,
                        "all_day": all_day,
                        "calendar_idx": cal_idx,
                    }
                    if end:
                        parsed_event['end'] = end

                    parsed_events.append(parsed_event)
            except Exception as e:
                logger.warning("Skipping calendar URL %s: %s", calendar_url, e)
                continue

        return parsed_events

    def get_view_range(self, view, current_dt, settings):
        """Compute the [start, end) datetime range to query for the given view."""
        tz = current_dt.tzinfo
        start = current_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if view == "timeGridDay":
            end = start + timedelta(days=1)
        elif view == "timeGridWeek":
            if settings.get("displayPreviousDays") == "true":
                week_start_day = int(settings.get("weekStartDay", 1))
                python_week_start = (week_start_day - 1) % 7
                offset = (current_dt.weekday() - python_week_start) % 7
                start = (current_dt - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif view == "dayGrid":
            start = (current_dt - timedelta(weeks=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = current_dt + timedelta(weeks=int(settings.get("displayWeeks") or 4))
        elif view == "dayGridMonth":
            start = datetime(current_dt.year, current_dt.month, 1, tzinfo=tz) - timedelta(weeks=1)
            end = datetime(current_dt.year, current_dt.month, 1, tzinfo=tz) + timedelta(weeks=6)
        elif view == "listMonth":
            end = start + timedelta(weeks=5)
        else:
            end = start + timedelta(days=1)
        return start, end

    def parse_data_points(self, event, tz):
        """Extract start/end ISO strings and the all-day flag from an iCal event."""
        all_day = False
        dtstart = event.decoded("dtstart")
        if isinstance(dtstart, datetime):
            start = dtstart.astimezone(tz).isoformat()
        else:
            start = dtstart.isoformat()
            all_day = True

        end = None
        if "dtend" in event:
            dtend = event.decoded("dtend")
            if isinstance(dtend, datetime):
                end = dtend.astimezone(tz).isoformat()
            else:
                end = dtend.isoformat()
        elif "duration" in event:
            duration = event.decoded("duration")
            end = (dtstart + duration).isoformat()
        return start, end, all_day

    def fetch_calendar(self, calendar_url):
        """Download and parse an iCalendar feed."""
        import icalendar

        # workaround for webcal urls
        if calendar_url.startswith("webcal://"):
            calendar_url = calendar_url.replace("webcal://", "https://")
        try:
            session = get_http_session()
            response = session.get(calendar_url, timeout=30)
            response.raise_for_status()
            return icalendar.Calendar.from_ical(response.text)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch iCalendar url: {str(e)}")

    @staticmethod
    def get_contrast_color(color):
        """Return '#000000' or '#ffffff' depending on which contrasts better with ``color``."""
        try:
            color = color.lstrip('#')
            r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        except (ValueError, IndexError):
            return '#ffffff'
        # YIQ formula to estimate brightness
        yiq = (r * 299 + g * 587 + b * 114) / 1000
        return '#000000' if yiq >= 150 else '#ffffff'

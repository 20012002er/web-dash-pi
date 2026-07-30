# DashPi (Web Edition)

[English](README.md) | [简体中文](README.zh-CN.md)

A web-based dashboard display system for Raspberry Pi (and any machine with a browser). DashPi renders dashboards as web pages — not by hijacking the Pi's framebuffer and drawing images like the original [OpenClaw-DashPi](https://github.com/OpenClaw-DashPi/OpenClaw-DashPi) — so the front-end runs directly in a desktop browser, and the back-end manages dashboards through a plugin system.

- **Version:** `3.0.0-web`
- **License:** Apache License 2.0
- **Language:** Python 3.10+ (Flask + Waitress)

---

## Highlights

- **Web-first rendering.** Each plugin provides a `dashboard.html` fragment and a `get_data()` API; the display shell (`/display`) polls `/api/current_state`, loads the active plugin's fragment, then fetches data from `/api/plugin/<id>/data`.
- **Plugin-based dashboards.** 26 built-in plugins across data, image, API-key, and special categories.
- **Loop scheduling preserved.** `LoopManager` / `Loop` / `PluginReference` keep the original scheduling logic (time-of-day, cross-midnight, priority, randomized weights, pre-computed "next").
- **Admin UI retained.** Manage plugins, loops, settings, API keys, and diagnostics from the browser.
- **No framebuffer / no Chromium kiosk / no WiFi manager.** Runs as a plain Flask + Waitress service.

## Architecture

```
Browser (Raspberry Pi desktop)
   │  /display (HTML shell)
   │  polls /api/current_state every 1s
   ▼
Flask + Waitress (src/dashpi.py)
   │  Blueprints: main, settings, plugin, loops, apikeys
   ▼
Plugin System (src/plugins/*)
   │  BasePlugin.get_data(settings, device_config) -> dict
   │  dashboard.html (frontend fragment)
   ▼
Config Layer (src/config.py + src/model.py)
   │  device.json (atomic writes, threading.Lock)
   │  LoopManager / RefreshInfo / loop_override
```

## Project Layout

```
web-dash-pi/
├── src/
│   ├── dashpi.py              # Flask entry (5 blueprints, waitress)
│   ├── config.py              # Atomic config writes, .env loader
│   ├── model.py               # RefreshInfo / LoopManager / Loop / PluginReference
│   ├── refresh_task.py        # Stateless state-query service
│   ├── blueprints/            # main / settings / plugin / loops / apikeys
│   ├── plugins/               # 26 plugins + base_plugin
│   ├── templates/             # Admin UI + display shell
│   ├── static/                # js, css, fonts, icons
│   └── utils/                 # app_utils, http_client, time_utils, ...
├── tests/                     # pytest suite
├── install/config_base/       # Initial device.json
├── requirements.txt
├── pytest.ini
├── VERSION
└── LICENSE
```

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run in development mode (port 8080)

```bash
python src/dashpi.py --dev
```

Open `http://<raspberry-pi-ip>:8080/` for the admin UI, or `http://<raspberry-pi-ip>:8080/display` for the full-screen dashboard.

### 3. Run in production mode (port 80)

```bash
sudo python src/dashpi.py
```

For auto-start on boot, run as a `systemd` service pointing to `python src/dashpi.py` (no `--dev` flag). No framebuffer hijack is required.

### 4. Open the dashboard in kiosk mode (optional)

On the Raspberry Pi desktop, launch the default browser full-screen at `http://localhost/display`:

```bash
chromium-browser --kiosk --noerrdialogs --disable-translate --no-first-run --fast --fast-start http://localhost/display
```

## Built-in Plugins (26)

| Category | Plugins |
| --- | --- |
| Data | clock, countdown, year_progress, todo_list, calendar, newspaper, comic, rss, wpotd, art_museum, astro_targets, iss_tracker, flight_tracker, github |
| Image | image_url, image_folder, image_upload, image_album, unsplash |
| API Key | weather, stocks, apod, ai_image, ai_text |
| Special | spotify_web (iframe embed, no kiosk), shazam_pi (experimental, getUserMedia) |

Each plugin directory contains:

- `<id>.py` — implements `get_data(settings, device_config) -> dict`
- `plugin-info.json` — plugin metadata
- `settings.html` — admin settings form fragment
- `dashboard.html` — front-end dashboard fragment (no `<html>`/`<head>`/`<body>` wrapper)
- `icon.png` — plugin icon
- `resources/`, `icons/`, helper modules — as needed

## Frontend Event Protocol

The display shell (`src/static/js/display.js`) dispatches the following events so each plugin's `dashboard.html` can be self-contained:

| Event | Fired When | Detail |
| --- | --- | --- |
| `plugin-dashboard-loaded` | Plugin fragment inserted into the container | `{ pluginId }` |
| `plugin-data` | Fresh data fetched from `/api/plugin/<id>/data` | `{ pluginId, data }` |
| `plugin-data-error` | Data fetch failed (HTTP 500) | `{ pluginId, error }` |

Plugins can also call these window helpers:

- `window.setDataRefreshInterval(ms)` — override the default 60s data refresh interval
- `window.refreshPluginData()` — force an immediate data refresh

## Configuration

`device.json` (in `src/config/` for dev, or `install/config_base/` for initial install):

```json
{
    "name": "DashPi",
    "timezone": "America/New_York",
    "time_format": "12h",
    "scheduler_sleep_time": 60,
    "startup": true,
    "loop_enabled": true,
    "loop_config": { "loops": [], "rotation_interval_seconds": 300, "active_loop": null },
    "refresh_info": { "refresh_time": null, "refresh_type": null, "plugin_id": null },
    "plugin_order": [],
    "proxy": { "enabled": false, "host": "", "port": "" }
}
```

API keys are stored in a `.env` file (read/written by the `apikeys` blueprint).

## API Reference (key endpoints)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Admin dashboard home |
| GET | `/display` | Full-screen display shell |
| GET | `/diagnostics` | Diagnostics page |
| GET | `/api/current_state` | `{plugin_id, loop_name, remaining_seconds, next_plugin_id, override, loop_enabled}` — polled every 1s |
| GET | `/api/plugin/<id>/data` | Plugin data JSON (calls `get_data()`) |
| GET | `/plugin/<id>/dashboard.html` | Plugin front-end fragment |
| GET | `/api/plugin_order` | Current plugin order |
| POST | `/toggle_loop` | Toggle the loop on/off |
| POST | `/api/skip_to_next` | Skip to next plugin |
| POST | `/api/pin_plugin` | Pin current plugin (override) |
| POST | `/api/clear_override` | Clear pin/override |
| GET | `/api/next_change_time` | Remaining seconds to next change |

## Testing

```bash
pytest
```

All tests live under `tests/`:

- `test_config.py` — config reads, atomic writes, no hardware keys
- `test_model.py` — `RefreshInfo`, `LoopManager` scheduling, midnight wrap, priority, randomize
- `test_current_state.py` — `/api/current_state` JSON structure
- `test_plugin_data_api.py` — `/api/plugin/<id>/data` (404 for unknown, success for `clock`)

## What Was Removed vs. OpenClaw-DashPi

| Removed | Reason |
| --- | --- |
| `src/display/` (DisplayManager, framebuffer hijack) | Replaced by browser rendering |
| `src/utils/image_loader.py`, `image_utils.py` | No PIL image generation |
| `src/utils/wifi_manager.py`, `wifi_display.py`, `bluetooth_manager.py` | No AP mode / WiFi onboarding needed |
| `src/blueprints/wifi.py`, `bluetooth.py` | Same as above |
| `static/images/current_image.png` | No more generated image |
| `AdaptiveImageLoader` injection in `BasePlugin` | Plugins return dicts, not PIL images |
| `generate_image()` on `BasePlugin` | Replaced by `get_data()` |
| Spotify Web kiosk subprocess management | Replaced by iframe embed |
| `RefreshInfo.image_hash` | No image to hash |
| Hardware keys in `device.json` (`display_type`, `resolution`, `orientation`, `inverted_image`, `brightness_schedule`, `display_transitions`) | No physical display |

## Acknowledgements

This project is a web-based rewrite of [OpenClaw-DashPi](https://github.com/OpenClaw-DashPi/OpenClaw-DashPi). All credit for the original architecture, plugin designs, and LoopManager scheduling goes to the OpenClaw-DashPi authors.

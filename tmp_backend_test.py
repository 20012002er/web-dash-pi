"""Backend smoke tests against running dev server."""
import requests
import json

BASE = "http://localhost:8080"

# Use a dedicated session for the smoke test and bypass macOS system proxies.
# The local dev server is reached directly; routing test traffic through a
# system proxy (e.g. 127.0.0.1:7890) causes misleading connection timeouts.
_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.proxies = {}


def check(name, method, path, expected_status=200, json_body=None, timeout=10):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = _SESSION.get(url, timeout=timeout)
        elif method == "POST":
            r = _SESSION.post(url, json=json_body, timeout=timeout)
        else:
            raise ValueError(method)
        ok = r.status_code == expected_status
        print(f"{'OK' if ok else 'FAIL'} {method} {path} -> {r.status_code}")
        if not ok:
            print(f"   body: {r.text[:200]}")
        return r
    except Exception as e:
        print(f"FAIL {method} {path} -> {e}")
        return None

print("=== Basic pages ===")
check("home", "GET", "/")
check("display", "GET", "/display")
check("diagnostics", "GET", "/diagnostics")
check("settings", "GET", "/settings")
check("api-keys", "GET", "/api-keys")
check("loops", "GET", "/loops")

print("\n=== State API ===")
r = check("current_state", "GET", "/api/current_state")
if r:
    data = r.json()
    print(f"   keys: {list(data.keys())}")
    print(f"   current_plugin: {data.get('current_plugin')}")

r = check("next_change_time", "GET", "/api/next_change_time")
if r:
    print(f"   data: {r.json()}")

print("\n=== Loop control ===")
check("toggle_loop", "POST", "/toggle_loop", json_body={"enabled": False})
check("toggle_loop", "POST", "/toggle_loop", json_body={"enabled": True})

print("\n=== Plugin data endpoints ===")
plugin_ids = [
    "ai_image", "ai_text", "apod", "art_museum", "astro_targets", "calendar",
    "clock", "comic", "countdown", "flight_tracker", "github", "image_album",
    "image_folder", "image_upload", "image_url", "iss_tracker", "newspaper",
    "rss", "shazam_pi", "spotify_web", "stocks", "todo_list", "unsplash",
    "weather", "wpotd", "year_progress"
]
for pid in plugin_ids:
    r = check(f"plugin_data_{pid}", "GET", f"/api/plugin/{pid}/data")
    if r and r.status_code == 200:
        try:
            body = r.json()
            if body.get("success"):
                print(f"   -> success, data keys: {list(body.get('data', {}).keys())[:8]}")
            else:
                print(f"   -> error: {body.get('error')}")
        except Exception:
            pass
    r2 = check(f"plugin_dashboard_{pid}", "GET", f"/plugin/{pid}/dashboard.html")

print("\n=== Loop management ===")
check("create_loop", "POST", "/create_loop", json_body={"name": "Test", "start_time": "00:00", "end_time": "24:00"})
check("add_plugin_to_loop", "POST", "/add_plugin_to_loop", json_body={"loop_name": "Test", "plugin_id": "clock", "refresh_interval_seconds": 60})
check("reorder_plugins", "POST", "/reorder_plugins", json_body={"loop_name": "Test", "plugin_ids": ["clock"]})
check("remove_plugin_from_loop", "POST", "/remove_plugin_from_loop", json_body={"loop_name": "Test", "plugin_id": "clock"})
check("delete_loop", "POST", "/delete_loop", json_body={"loop_name": "Test"})

print("\n=== Override ===")
check("pin_plugin", "POST", "/api/pin_plugin", json_body={"plugin_id": "clock"})
check("clear_override", "POST", "/api/clear_override")

print("\n=== 404 ===")
check("plugin_not_found", "GET", "/api/plugin/nonexistent/data", expected_status=404)

print("\nDone.")

#!/usr/bin/env python3
"""DashPi — main Flask application entry point for the web dashboard.

Initializes the config, refresh task (state service), and plugin system, then
serves the web UI via Waitress. Supports ``--dev`` mode for local development
on port 8080 using ``device_dev.json``. Unlike the original OpenClaw-DashPi
entry point, this version does not manage a physical display, WiFi, or
Bluetooth — the dashboard is rendered in the browser.
"""

# set up logging
import os
import logging.config

logging.config.fileConfig(os.path.join(os.path.dirname(__file__), 'config', 'logging.conf'))

import argparse
import logging

from flask import Flask
from config import Config
from refresh_task import RefreshTask
from blueprints.main import main_bp
from blueprints.settings import settings_bp
from blueprints.plugin import plugin_bp
from blueprints.loops import loops_bp
from blueprints.apikeys import apikeys_bp
from jinja2 import ChoiceLoader, FileSystemLoader
from plugins.plugin_registry import load_plugins
from waitress import serve

logger = logging.getLogger(__name__)

# Parse command line arguments
parser = argparse.ArgumentParser(description='DashPi Web Display Server')
parser.add_argument('--dev', action='store_true', help='Run in development mode')
args = parser.parse_args()

# Set development mode settings
if args.dev:
    Config.config_file = os.path.join(Config.BASE_DIR, "config", "device_dev.json")
    DEV_MODE = True
    PORT = 8080
    logger.info("Starting in DEVELOPMENT mode on port 8080")
else:
    DEV_MODE = False
    PORT = 80
    logger.info("Starting in PRODUCTION mode on port 80")
logging.getLogger('waitress.queue').setLevel(logging.ERROR)

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64MB upload limit (config backups with images)
# Allow plugin dashboard.html / settings.html fragments to be loaded from the plugins directory
template_dirs = [
    os.path.join(os.path.dirname(__file__), "templates"),    # Default template folder
    os.path.join(os.path.dirname(__file__), "plugins"),      # Plugin templates
]
app.jinja_loader = ChoiceLoader([FileSystemLoader(directory) for directory in template_dirs])

device_config = Config()
refresh_task = RefreshTask(device_config)

load_plugins(device_config.get_plugins())

# Store dependencies for blueprint access
app.config['DEVICE_CONFIG'] = device_config
app.config['REFRESH_TASK'] = refresh_task

# Set additional parameters
app.config['MAX_FORM_PARTS'] = 10_000

# Register Blueprints
app.register_blueprint(main_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(plugin_bp)
app.register_blueprint(apikeys_bp)
app.register_blueprint(loops_bp)


# Inject project_name and version into all templates
@app.context_processor
def inject_globals():
    try:
        from blueprints.main import get_version
        version = get_version()
    except Exception:
        version = ""
    return dict(project_name="DashPi", version=version)


# Security headers — allow inline scripts/styles so plugin dashboard.html
# fragments can ship self-contained <style>/<script> blocks, while still
# restricting everything else to same-origin.
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self'"
    )
    return response


if __name__ == '__main__':
    try:
        app.secret_key = os.urandom(24).hex()
        if DEV_MODE:
            logger.info("Serving on http://0.0.0.0:8080")
            # use_reloader=False: the reloader spawns a child process that
            # shares the config file with the parent. On shutdown both
            # processes write_config() concurrently, which corrupts
            # device_dev.json. Disabling the reloader keeps a single process.
            app.run(host="0.0.0.0", port=8080, debug=True, use_reloader=False)
        else:
            logger.info("Serving on http://0.0.0.0:%d", PORT)
            serve(app, host="0.0.0.0", port=PORT, threads=4)
    finally:
        # Persist final config on shutdown
        logger.info("Writing final config on shutdown")
        device_config.write_config()

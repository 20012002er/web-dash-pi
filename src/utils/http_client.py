"""
HTTP Client with Connection Pooling for DashPi

Provides a shared requests.Session() instance for all plugins to use.
Benefits:
- Connection reuse (20-30% faster requests)
- Reduced TCP handshake overhead
- Automatic keep-alive handling
- Consistent headers across all requests

Proxy support:
- Reads proxy settings from ``device.json`` (``proxy.enabled``, ``proxy.host``,
  ``proxy.port``). When enabled, routes HTTP/HTTPS through the configured proxy
  while keeping local/LAN traffic direct via ``NO_PROXY``.
- When proxy is disabled, bypasses system proxies entirely (for self-hosted
  services like Immich on the same LAN).

Usage:
    from utils.http_client import get_http_session

    session = get_http_session()
    response = session.get(url)
"""

import json
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Local/LAN addresses that should never go through the proxy
_NO_PROXY = "127.0.0.1,localhost,::1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"

# Global session instance (singleton)
_HTTP_SESSION: Optional[requests.Session] = None


def _read_proxy_config() -> dict:
    """Read proxy configuration from device.json.

    Tries ``device_dev.json`` first (development), then ``device.json``
    (production). Returns a dict with ``enabled``, ``host``, ``port`` keys.
    """
    # Find the project root (two levels up from this file: utils/ -> src/ -> project/)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_dir = os.path.join(project_root, "src", "config")

    for filename in ("device_dev.json", "device.json"):
        config_path = os.path.join(config_dir, filename)
        if os.path.isfile(config_path):
            try:
                with open(config_path) as f:
                    data = json.load(f)
                return data.get("proxy", {})
            except Exception as e:
                logger.debug(f"Failed to read {config_path}: {e}")

    return {}


def get_http_session() -> requests.Session:
    """
    Get the shared HTTP session instance.
    Creates it on first call (lazy initialization).

    Proxy behavior:
    - If ``proxy.enabled`` is true in device.json, routes through the
      configured proxy while keeping local/LAN traffic direct.
    - If disabled (default), bypasses system proxies entirely.

    Returns:
        requests.Session: Shared session with connection pooling
    """
    global _HTTP_SESSION

    if _HTTP_SESSION is None:
        logger.debug("Initializing shared HTTP session with connection pooling")
        _HTTP_SESSION = requests.Session()

        proxy_cfg = _read_proxy_config()

        if proxy_cfg.get("enabled") and proxy_cfg.get("host") and proxy_cfg.get("port"):
            # Proxy enabled — route external traffic through proxy,
            # keep local/LAN traffic direct.
            host = proxy_cfg["host"].strip()
            port = proxy_cfg["port"].strip()
            proxy_url = f"http://{host}:{port}"
            _HTTP_SESSION.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            _HTTP_SESSION.trust_env = False
            os.environ["NO_PROXY"] = _NO_PROXY
            os.environ["no_proxy"] = _NO_PROXY
            logger.info(f"HTTP session proxy enabled: {proxy_url}")
        else:
            # Proxy disabled — bypass system proxies entirely.
            # Many DashPi plugins talk to self-hosted services (Immich, Spotify, etc.)
            # on the same machine or LAN — routing those through a system proxy causes
            # 502 errors. ``trust_env=False`` makes requests ignore HTTP_PROXY /
            # HTTPS_PROXY env vars AND the macOS System Configuration proxies.
            _HTTP_SESSION.trust_env = False
            _HTTP_SESSION.proxies = {}
            logger.debug("HTTP session proxy disabled (direct connections)")

        # Set common headers for all DashPi requests
        _HTTP_SESSION.headers.update({
            'User-Agent': 'DashPi/2.0 (https://github.com/SHagler2/DashPi/)'
        })

        # Configure connection pool with proper retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],  # Only retry idempotent methods
        )
        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=4,
            max_retries=retry_strategy,
            pool_block=False
        )
        _HTTP_SESSION.mount('http://', adapter)
        _HTTP_SESSION.mount('https://', adapter)

        logger.debug("HTTP session initialized successfully")

    return _HTTP_SESSION


def close_http_session():
    """
    Close the shared HTTP session.
    Should be called on application shutdown.
    """
    global _HTTP_SESSION

    if _HTTP_SESSION is not None:
        logger.debug("Closing shared HTTP session")
        _HTTP_SESSION.close()
        _HTTP_SESSION = None

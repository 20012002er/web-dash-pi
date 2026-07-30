"""Stocks plugin — displays a stock ticker dashboard with price charts.

Ported from the original OpenClaw-DashPi project. The original implementation
rendered stock cards as a PIL image with a sparkline per ticker. This web
version keeps all of the data-fetching logic (akshare for US stocks, market
hours detection, instance-level caching with market-aware TTL) and returns
the parsed data as a JSON-serializable dict for the frontend
``dashboard.html`` fragment to render. The PIL rendering helpers, the
``image_loader``, and the grid-layout calculations have been removed.

``get_loop_weight()`` is preserved so the plugin is selected less often when
the market is closed (if the user opts in via ``reduceWhenClosed``).
"""

import logging
import time
from datetime import datetime, date
from zoneinfo import ZoneInfo

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

# Cache TTL: shorter when market open, longer when closed
CACHE_TTL_MARKET_OPEN = 60
CACHE_TTL_MARKET_CLOSED = 3600

# User-selectable font size multipliers applied to all text in the plugin
FONT_SIZES = {
    "x-small": 0.6,
    "small": 0.8,
    "normal": 1,
    "large": 1.25,
    "x-large": 1.5
}

# Additional scale factors applied per stock count to prevent text overflow in small cells
COUNT_SCALES = {1: 1.7, 2: 1.35, 3: 1.2, 4: 1.15, 5: 0.9, 6: 0.85}
# Grid column counts by number of stocks (max 6)
GRID_COLUMNS = {1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3}


def format_large_number(num):
    """Format large numbers with K, M, B, T suffixes."""
    if num is None:
        return "N/A"
    for threshold, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if num >= threshold:
            return f"{num / threshold:.2f}{suffix}"
    return str(num)


def format_price(value):
    """Format a price value or return N/A."""
    return f"${value:,.2f}" if value is not None else "N/A"


# Exchange prefixes used by akshare's stock_us_hist (East Money coding).
# 105=NASDAQ, 106=NYSE, 107=AMEX. We try each in order until one returns data.
_US_EXCHANGE_PREFIXES = ["105", "106", "107"]


def _fetch_us_hist_with_prefix(ak, symbol, start_date, end_date):
    """Fetch US stock daily history, trying each exchange prefix.

    akshare's stock_us_hist requires a full code like '105.AAPL' but the user
    only provides the bare symbol 'AAPL'. We try each known prefix and return
    the first non-empty DataFrame. Returns None if no prefix works.
    """
    for prefix in _US_EXCHANGE_PREFIXES:
        full_code = f"{prefix}.{symbol}"
        try:
            hist = ak.stock_us_hist(
                symbol=full_code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq",
            )
            if hist is not None and len(hist) > 0:
                return hist
        except Exception:
            continue
    return None


def _fetch_us_stock_name(ak, symbol):
    """Fetch the short display name for a US stock via Xueqiu data source.

    Returns the Chinese short name (e.g. '苹果' for AAPL), falling back to
    the English short name, or None if unavailable.
    """
    try:
        info = ak.stock_individual_basic_info_us_xq(symbol=symbol)
        items = dict(zip(info["item"], info["value"]))
        return (
            items.get("org_short_name_cn")
            or items.get("org_short_name_en")
            or items.get("org_name_cn")
            or items.get("org_name_en")
        )
    except Exception as e:
        logger.debug(f"Could not fetch name for {symbol}: {e}")
        return None


# NYSE market holidays by year
# Source: https://www.nyse.com/markets/hours-calendars
# Early-close days (1 PM ET) are not tracked — treated as normal open days
NYSE_HOLIDAYS = {
    2025: {
        date(2025, 1, 1),    # New Year's Day
        date(2025, 1, 20),   # MLK Jr. Day
        date(2025, 2, 17),   # Presidents' Day
        date(2025, 4, 18),   # Good Friday
        date(2025, 5, 26),   # Memorial Day
        date(2025, 6, 19),   # Juneteenth
        date(2025, 7, 4),    # Independence Day
        date(2025, 9, 1),    # Labor Day
        date(2025, 11, 27),  # Thanksgiving
        date(2025, 12, 25),  # Christmas
    },
    2026: {
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # MLK Jr. Day
        date(2026, 2, 16),   # Presidents' Day
        date(2026, 4, 3),    # Good Friday
        date(2026, 5, 25),   # Memorial Day
        date(2026, 6, 19),   # Juneteenth
        date(2026, 7, 3),    # Independence Day (observed)
        date(2026, 9, 7),    # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    },
    2027: {
        date(2027, 1, 1),    # New Year's Day
        date(2027, 1, 18),   # MLK Jr. Day
        date(2027, 2, 15),   # Presidents' Day
        date(2027, 3, 26),   # Good Friday
        date(2027, 5, 31),   # Memorial Day
        date(2027, 6, 18),   # Juneteenth (observed)
        date(2027, 7, 5),    # Independence Day (observed)
        date(2027, 9, 6),    # Labor Day
        date(2027, 11, 25),  # Thanksgiving
        date(2027, 12, 24),  # Christmas (observed)
    },
}


def _is_nyse_holiday(today):
    """Check if a date is a known NYSE holiday."""
    return today in NYSE_HOLIDAYS.get(today.year, set())


def is_market_open():
    """Check if US stock market (NYSE/NASDAQ) is currently open.

    Open Monday-Friday, 9:30 AM - 4:00 PM Eastern Time.
    Accounts for weekends and NYSE holidays (2025-2027).
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    if _is_nyse_holiday(now_et.date()):
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et < market_close


class Stocks(BasePlugin):
    """Stock ticker dashboard plugin using akshare.

    Fetches up to 6 US stock tickers via akshare (backed by East Money, which
    is accessible from mainland China unlike yfinance). Returns the data as a
    JSON-serializable dict for the frontend to render as a responsive card
    grid with sparkline charts.
    """

    @staticmethod
    def get_loop_weight(settings):
        """Reduce selection weight when market is closed, if user enabled the option."""
        if settings.get('reduceWhenClosed') == 'true' and not is_market_open():
            return 0.2
        return 1.0

    def __init__(self, config, **dependencies):
        super().__init__(config, **dependencies)
        self._stocks_cache = None
        self._stocks_cache_time = 0
        self._stocks_cache_tickers = None

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        template_params['hide_refresh_interval'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Fetch stock data via akshare and return it for the frontend.

        Args:
            settings: Plugin settings dict containing ``title``, ``tickers``,
                ``autoRefresh``, ``fontSize``, and ``reduceWhenClosed``.
            device_config: Device configuration object, used to look up
                ``stocks_saved_tickers`` and the configured timezone.

        Returns:
            dict: ``{stocks: [{symbol, name, price, change, change_percent,
            hist: [float]}], market_open: bool, units: str}``.
        """
        title = settings.get("title", "Stock Prices")
        tickers_input = settings.get("tickers", "")

        # Get saved tickers from device config
        saved_tickers_raw = device_config.get_config("stocks_saved_tickers", default=[])
        # Extract symbols from saved tickers (handle both old string format and new dict format)
        saved_tickers = [t["symbol"] if isinstance(t, dict) else t for t in saved_tickers_raw]

        # Parse comma-separated tickers from input (if any)
        input_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()] if tickers_input else []

        # Use input tickers if provided, otherwise fall back to saved tickers
        tickers = input_tickers if input_tickers else saved_tickers

        if not tickers:
            raise RuntimeError("No tickers configured. Add tickers in the plugin settings.")

        # Fetch stock data (limit to 6 tickers)
        stocks_data = self.fetch_stock_data(tickers[:6])

        if not stocks_data:
            raise RuntimeError("Could not fetch data for any of the provided ticker symbols.")

        market_open = is_market_open()

        logger.info("=== Stocks Plugin: Data fetch complete ===")
        return {
            "title": title,
            "stocks": stocks_data,
            "market_open": market_open,
            "units": "USD",
        }

    def fetch_stock_data(self, tickers):
        """Fetch stock data for a list of ticker symbols using akshare.

        Uses akshare (backed by East Money / Sina, accessible from mainland
        China) instead of yfinance (Yahoo Finance, blocked in mainland China
        since 2021).

        For each ticker, fetches ~1 year of daily OHLCV history via
        stock_us_hist() (~0.5s per ticker) and derives all display fields:
          - current price  = latest day's close
          - change / pct   = latest day's 涨跌额 / 涨跌幅
          - day high/low   = latest day's 最高 / 最低
          - 52W high/low   = max/min over the full history range
          - volume         = latest day's 成交量
          - hist           = list of close prices for the sparkline chart

        Stock names are fetched once per ticker via
        stock_individual_basic_info_us_xq() and cached on the instance.

        Results are cached with a TTL that varies by market status (shorter
        when open, longer when closed).
        """
        import akshare as ak
        from datetime import datetime as _dt, timedelta as _td

        # Check cache
        now = time.monotonic()
        cache_ttl = CACHE_TTL_MARKET_OPEN if is_market_open() else CACHE_TTL_MARKET_CLOSED
        if (self._stocks_cache is not None
                and self._stocks_cache_tickers == tickers
                and now - self._stocks_cache_time < cache_ttl):
            logger.info(f"Using cached stock data ({now - self._stocks_cache_time:.0f}s old)")
            return self._stocks_cache

        stocks_data = []
        end_date = _dt.now().strftime('%Y%m%d')
        start_date = (_dt.now() - _td(days=365)).strftime('%Y%m%d')

        # Ensure the per-instance name cache exists
        if not hasattr(self, '_name_cache'):
            self._name_cache = {}

        for symbol in tickers:
            try:
                hist = _fetch_us_hist_with_prefix(ak, symbol, start_date, end_date)
                if hist is None or len(hist) == 0:
                    logger.warning(f"Could not fetch history for '{symbol}'")
                    continue

                last = hist.iloc[-1]
                current_price = float(last['收盘'])
                change = float(last.get('涨跌额') or 0)
                change_percent = float(last.get('涨跌幅') or 0)
                day_high = last.get('最高')
                day_low = last.get('最低')
                volume = last.get('成交量')

                week52_high = float(hist['最高'].max()) if len(hist) > 0 else None
                week52_low = float(hist['最低'].min()) if len(hist) > 0 else None

                # Sparkline history: recent closes (cap at ~60 trading days)
                try:
                    closes = [float(x) for x in hist['收盘'].tail(60).tolist()]
                except Exception:
                    closes = [current_price]

                # Fetch display name (cached per-instance to avoid repeat calls)
                name = self._name_cache.get(symbol)
                if not name:
                    name = _fetch_us_stock_name(ak, symbol) or symbol
                    self._name_cache[symbol] = name

                stocks_data.append({
                    "symbol": symbol,
                    "name": name,
                    "price": current_price,
                    "change": round(change, 2),
                    "change_percent": round(change_percent, 2),
                    "volume": format_large_number(volume),
                    "high": float(day_high) if day_high is not None else None,
                    "low": float(day_low) if day_low is not None else None,
                    "week52_high": week52_high,
                    "week52_low": week52_low,
                    "hist": closes,
                    "is_positive": change >= 0,
                })

            except Exception as e:
                logger.error(f"Error processing data for {symbol}: {str(e)}")
                continue

        # Update cache
        if stocks_data:
            self._stocks_cache = stocks_data
            self._stocks_cache_time = now
            self._stocks_cache_tickers = tickers

        return stocks_data

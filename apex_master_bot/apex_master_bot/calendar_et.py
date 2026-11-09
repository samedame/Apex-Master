"""Trading-day helpers. NYSE holidays are read from market_holidays.txt (you maintain it); half-days are
listed here because the tested pipeline skips sessions shorter than 60 bars."""
import datetime as dt
import os
from zoneinfo import ZoneInfo
from .config import TZ

NY = ZoneInfo(TZ)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # .../apex_master_bot
HALF_DAYS = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}                                  # 13:00 ET closes
OPEN_T, CLOSE_T = dt.time(9, 30), dt.time(16, 0)


def _lines(path):
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {l.split("#")[0].strip() for l in f if l.split("#")[0].strip()}


def holidays():
    return _lines(os.path.join(BASE, "market_holidays.txt"))


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in holidays() and d.isoformat() not in HALF_DAYS


def now_et() -> dt.datetime:
    return dt.datetime.now(NY)


def session_close(day: dt.date) -> dt.time:
    """Regular-session close for a known session, including 13:00 ET half-days."""
    return dt.time(13) if day.isoformat() in HALF_DAYS else CLOSE_T

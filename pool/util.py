import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config

IST = ZoneInfo("Asia/Kolkata")


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    """ISO time from Kalshi or the sheet -> aware UTC datetime, or None."""
    if not s:
        return None
    s = str(s).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_prob(v):
    """'0.62', '62%', '62' -> 0.62. Returns None if it isn't a usable probability."""
    if v is None:
        return None
    s = str(v).strip().rstrip("%").strip()
    try:
        p = float(s)
    except ValueError:
        return None
    if p > 1:
        p /= 100.0
    if not (0.01 <= p <= 0.99):
        return None
    return round(p, 4)


def clamp_prob(p):
    return round(min(0.99, max(0.01, p)), 4)


def to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fee(contracts, price):
    """Kalshi general taker fee, rounded up to the next cent."""
    raw = config.FEE_RATE * contracts * price * (1 - price)
    return math.ceil(round(raw * 100, 6)) / 100.0


def mid(snap):
    yb, ya = snap.get("yes_bid"), snap.get("yes_ask")
    if yb is not None and ya is not None and 0 < ya - yb <= 0.2:
        return round((yb + ya) / 2, 4)
    lp = snap.get("last_price")
    if lp:
        return round(lp, 4)
    if yb is not None and ya is not None:
        return round((yb + ya) / 2, 4)
    return None


def cell(v):
    """Value for a sheet cell: blank for None, rounded floats."""
    if v is None:
        return ""
    if isinstance(v, float):
        return round(v, 4)
    return v

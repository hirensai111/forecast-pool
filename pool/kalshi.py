"""Read-only client for Kalshi's public market-data API. It never logs in and never places orders."""
import time

import requests

from . import config


def num(market, key):
    """Price-like field as a float in dollars. Prefers the *_dollars / *_fp fields, falls back to cents."""
    for k in (f"{key}_dollars", f"{key}_fp"):
        v = market.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    v = market.get(key)
    if v in (None, ""):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    # Legacy integer price fields are in cents; counts (volume, open interest) are not.
    if key in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price"):
        return v / 100.0
    return v


def best_level(levels):
    """Highest-priced bid level from [[price, count], ...]; returns (price, count) or (None, 0)."""
    best = (None, 0.0)
    for lvl in levels or []:
        try:
            p, c = float(lvl[0]), float(lvl[1])
        except (TypeError, ValueError, IndexError):
            continue
        if best[0] is None or p > best[0]:
            best = (p, c)
    return best


def parse_orderbook(payload):
    """Kalshi returns bids only. YES ask = 1 - best NO bid, and its size is that bid's size."""
    ob = payload.get("orderbook_fp") or {}
    yes_lv, no_lv = ob.get("yes_dollars"), ob.get("no_dollars")
    if yes_lv is None and no_lv is None:
        ob = payload.get("orderbook") or {}
        yes_lv, no_lv = ob.get("yes_dollars"), ob.get("no_dollars")
    yb, yb_qty = best_level(yes_lv)
    nb, nb_qty = best_level(no_lv)
    return {
        "yes_bid": yb, "no_bid": nb,
        "yes_ask": round(1 - nb, 4) if nb is not None else None,
        "no_ask": round(1 - yb, 4) if yb is not None else None,
        "yes_ask_depth": nb_qty, "no_ask_depth": yb_qty,
    }


class Kalshi:
    def __init__(self, base=None, pause=None, session=None):
        self.base = (base or config.KALSHI_BASE).rstrip("/")
        self.pause = config.REQUEST_PAUSE_S if pause is None else pause
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = "forecast-pool/1.0 (educational, read-only)"

    def _get(self, path, params=None, allow_404=False):
        for attempt in range(4):
            time.sleep(self.pause)
            r = self.s.get(f"{self.base}{path}", params=params, timeout=30)
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return None

    def open_events(self, max_pages=150):
        """All open events with their markets nested. Each event carries a category."""
        events, cursor = [], None
        for _ in range(max_pages):
            params = {"status": "open", "with_nested_markets": "true", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/events", params)
            events.extend(data.get("events") or [])
            cursor = data.get("cursor")
            if not cursor:
                break
        return events

    def markets(self, tickers):
        """Current market records for a list of tickers."""
        out = {}
        tickers = list(dict.fromkeys(t for t in tickers if t))
        for i in range(0, len(tickers), 50):
            chunk = tickers[i:i + 50]
            data = self._get("/markets", {"tickers": ",".join(chunk), "limit": 1000})
            for m in data.get("markets") or []:
                out[m["ticker"]] = m
        return out

    def market(self, ticker):
        """One market, falling back to the historical archive for old settled markets."""
        data = self._get(f"/markets/{ticker}", allow_404=True)
        if data is None:
            data = self._get(f"/historical/markets/{ticker}", allow_404=True)
        return (data or {}).get("market")

    def orderbook(self, ticker, depth=5):
        data = self._get(f"/markets/{ticker}/orderbook", {"depth": depth}, allow_404=True)
        return parse_orderbook(data or {})

"""Collector: refreshes the Candidates tab and snapshots prices for the active slate."""
from datetime import timedelta

from . import config
from .kalshi import num
from .util import cell, iso, mid, parse_time


def refresh_candidates(kalshi, ledger, now):
    """Binary markets in the five categories, closing within 14 days, priced between 2 and 98 cents."""
    horizon = now + timedelta(days=config.CANDIDATE_MAX_DAYS)
    by_cat = {}
    for e in kalshi.open_events():
        cat = config.CATEGORY_MAP.get((e.get("category") or "").strip().lower())
        if not cat:
            continue
        for m in e.get("markets") or []:
            if (m.get("market_type") or "binary") != "binary":
                continue
            if (m.get("status") or "").lower() not in ("open", "active"):
                continue
            close = parse_time(m.get("close_time"))
            if not close or not (now < close <= horizon):
                continue
            ya = num(m, "yes_ask")
            if ya is None or not (config.CANDIDATE_MIN_PRICE <= ya <= config.CANDIDATE_MAX_PRICE):
                continue
            vol = num(m, "volume_24h") or 0.0
            series = (e.get("series_ticker") or m.get("event_ticker") or "").lower()
            by_cat.setdefault(cat, []).append((vol, [
                iso(now), m["ticker"], m.get("event_ticker") or e.get("event_ticker", ""), cat,
                e.get("title") or m.get("title") or "",
                m.get("yes_sub_title") or m.get("subtitle") or "",
                iso(close), cell(num(m, "yes_bid")), cell(ya), cell(num(m, "last_price")),
                cell(vol), cell(num(m, "open_interest")),
                (m.get("rules_primary") or "")[:config.RULES_MAX_CHARS],
                f"https://kalshi.com/markets/{series}" if series else "",
            ]))
    rows = []
    for cat in sorted(by_cat):
        top = sorted(by_cat[cat], key=lambda x: -x[0])[:config.CANDIDATES_PER_CATEGORY]
        rows.extend(r for _, r in top)
    ledger.replace("Candidates", rows)
    return len(rows)


def active_slate(ledger, now):
    """Slate rows whose market has not closed yet, one per ticker."""
    out = {}
    for r in ledger.records("Slate"):
        t = (r.get("ticker") or "").strip().upper()
        close = parse_time(r.get("close_time_utc"))
        if t and close and close > now and t not in out:
            out[t] = {"ticker": t, "category": r.get("category", ""), "title": r.get("title", ""),
                      "close": close}
    return out


def snapshot(kalshi, ledger, now):
    """Price + order-book snapshot for every active slate market. Returns {ticker: snapshot}."""
    active = active_slate(ledger, now)
    if not active:
        ledger.replace("Latest", [])
        return {}
    markets = kalshi.markets(list(active))
    snaps, snap_rows, latest_rows = {}, [], []
    for t, info in active.items():
        m = markets.get(t)
        if not m:
            continue
        ob = kalshi.orderbook(t)
        s = {
            "ticker": t, "category": info["category"], "title": info["title"],
            "close": info["close"], "status": (m.get("status") or "").lower(),
            "yes_bid": ob["yes_bid"] if ob["yes_bid"] is not None else num(m, "yes_bid"),
            "yes_ask": ob["yes_ask"] if ob["yes_ask"] is not None else num(m, "yes_ask"),
            "no_bid": ob["no_bid"] if ob["no_bid"] is not None else num(m, "no_bid"),
            "no_ask": ob["no_ask"] if ob["no_ask"] is not None else num(m, "no_ask"),
            "yes_ask_depth": ob["yes_ask_depth"], "no_ask_depth": ob["no_ask_depth"],
            "last_price": num(m, "last_price"), "volume_24h": num(m, "volume_24h"),
            "open_interest": num(m, "open_interest"),
        }
        s["mid"] = mid(s)
        snaps[t] = s
        snap_rows.append([iso(now), t, s["status"]] + [cell(s[k]) for k in (
            "yes_bid", "yes_ask", "no_bid", "no_ask", "last_price", "mid",
            "yes_ask_depth", "no_ask_depth", "volume_24h", "open_interest")])
        latest_rows.append([iso(now), t, info["title"], cell(s["yes_bid"]), cell(s["yes_ask"]),
                            cell(s["mid"]), iso(info["close"])])
    ledger.append("Snapshots", snap_rows)
    ledger.replace("Latest", latest_rows)
    return snaps

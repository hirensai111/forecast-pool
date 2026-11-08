"""Scorer: Brier score against the market, calibration and paper P&L, per bot and per category.

Each market counts once per bot: a bot's rows on one market are averaged first, then markets are
averaged, so a bot that updates often doesn't outweigh one that forecasts twice a day.
"""
import math
from collections import defaultdict

from . import config
from .util import cell, iso, to_float


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def load_forecasts(ledger, results):
    """{bot: [(ticker, p, mid_at_seen), ...]} for valid forecasts on markets settled yes/no."""
    out = defaultdict(list)
    tabs = [(f"F_{b}", b) for b in config.FORECASTERS] + [("F_Baselines", None)]
    for tab, bot in tabs:
        for r in ledger.records(tab):
            if not str(r.get("check", "")).startswith("ok"):
                continue
            t = r.get("ticker", "").strip().upper()
            if t not in results:
                continue
            p = to_float(r.get("prob_yes"))
            if p is None:
                continue
            p = p / 100 if p > 1 else p
            out[bot or r.get("bot")].append((t, p, to_float(r.get("mid_at_seen"))))
    return out


def brier_block(rows, results):
    """rows: [(ticker, p, mid)] -> dict of scores (per-market averaged)."""
    per_m = defaultdict(list)
    for t, p, m in rows:
        per_m[t].append((p, m))
    b, mb_pair, bb_pair, ll = [], [], [], []
    for t, items in per_m.items():
        y = 1.0 if results[t] == "yes" else 0.0
        b.append(_mean([(p - y) ** 2 for p, _ in items]))
        ll.append(_mean([-math.log(min(0.999, max(0.001, p if y else 1 - p))) for p, _ in items]))
        paired = [(p, m) for p, m in items if m is not None]
        if paired:
            bb_pair.append(_mean([(p - y) ** 2 for p, _ in paired]))
            mb_pair.append(_mean([(m - y) ** 2 for _, m in paired]))
    bb, mb = _mean(bb_pair), _mean(mb_pair)
    return {
        "markets": len(per_m), "forecasts": len(rows), "brier": _mean(b),
        "market_brier": mb, "vs_market": (bb - mb) if bb is not None and mb is not None else None,
        "log_loss": _mean(ll),
    }


def trade_block(trades):
    settled = [t for t in trades if t.get("status") == "settled" and t.get("result") != "void"]
    open_ = [t for t in trades if t.get("status") == "open"]
    pnl = sum(to_float(t.get("pnl"), 0) for t in settled)
    staked = sum(to_float(t.get("cost"), 0) + to_float(t.get("fee"), 0) for t in settled)
    wins = sum(1 for t in settled if to_float(t.get("pnl"), 0) > 0)
    return {"settled": len(settled), "open": len(open_), "pnl": round(pnl, 2),
            "win_rate": wins / len(settled) if settled else None,
            "roi": pnl / staked if staked else None}


def score(ledger, now):
    res_rows = ledger.records("Results")
    results = {r["ticker"]: r["result"] for r in res_rows if r.get("result") in ("yes", "no")}
    cats = {r["ticker"]: r.get("category", "") for r in res_rows}
    forecasts = load_forecasts(ledger, results)
    trades = ledger.records("Trades")
    stamp = iso(now)

    board = []
    for bot in config.ALL_BOTS:
        s = brier_block(forecasts.get(bot, []), results)
        tr = trade_block([t for t in trades if t.get("bot") == bot])
        if bot == "Market" and s["brier"] is not None:
            s["vs_market"] = 0.0
        ready = "yes" if s["forecasts"] >= config.READY_AT else f"{s['forecasts']}/{config.READY_AT}"
        board.append([stamp, bot, s["markets"], s["forecasts"], cell(s["brier"]),
                      cell(s["market_brier"]), cell(s["vs_market"]), cell(s["log_loss"]),
                      tr["settled"], tr["open"], cell(tr["win_rate"]), tr["pnl"], cell(tr["roi"]),
                      ready])
    board.sort(key=lambda r: (r[6] == "", r[6] if r[6] != "" else 0))
    ledger.replace("Scoreboard", board)

    by_cat = []
    for bot in config.ALL_BOTS:
        for cat in sorted({c for c in cats.values() if c}):
            rows = [x for x in forecasts.get(bot, []) if cats.get(x[0]) == cat]
            if not rows:
                continue
            s = brier_block(rows, results)
            tr = trade_block([t for t in trades if t.get("bot") == bot and t.get("category") == cat])
            if bot == "Market":
                s["vs_market"] = 0.0
            by_cat.append([stamp, bot, cat, s["markets"], cell(s["brier"]), cell(s["market_brier"]),
                           cell(s["vs_market"]), tr["settled"], tr["pnl"]])
    ledger.replace("ByCategory", by_cat)

    calib = []
    for bot in config.ALL_BOTS:
        buckets = defaultdict(list)
        for t, p, _ in forecasts.get(bot, []):
            buckets[min(9, int(p * 10))].append((p, 1.0 if results[t] == "yes" else 0.0))
        for b in sorted(buckets):
            items = buckets[b]
            calib.append([stamp, bot, f"{b * 10}-{b * 10 + 10}%", len(items),
                          cell(_mean([p for p, _ in items])), cell(_mean([y for _, y in items]))])
    ledger.replace("Calibration", calib)
    return board

"""Paper trader: stamps new forecasts, turns them into paper trades by a fixed rule, and settles trades.

No bot ever trades. A bot only writes a probability; this script decides, with the same rule for
everyone, whether that probability earns a paper position.
"""
import math

from . import config
from .collector import active_slate
from .util import cell, clamp_prob, fee, iso, parse_prob, parse_time, to_float


# ---------- positions ----------

class Book:
    """Every bot's paper positions, loaded from the Trades tab."""

    def __init__(self, ledger):
        self.rows = ledger.records("Trades")
        self.new = []

    def all(self):
        return self.rows + self.new

    def cash(self, bot):
        c = config.BANKROLL
        for t in self.all():
            if t.get("bot") != bot:
                continue
            if t.get("status") == "settled":
                c += to_float(t.get("pnl"), 0.0)
            else:
                c -= to_float(t.get("cost"), 0.0) + to_float(t.get("fee"), 0.0)
        return c

    def holds(self, bot, ticker):
        return any(t.get("bot") == bot and t.get("ticker") == ticker for t in self.all())

    def next_id(self):
        return f"T{len(self.all()) + 1:05d}"

    def open_position(self, now, bot, snap, side, price, depth, prob):
        """Size within the per-market cap, the bot's cash and the visible depth. Returns trade id or None."""
        if price is None or not (0 < price < 1):
            return None, "no price"
        budget = min(config.MAX_PER_MARKET, self.cash(bot))
        per = price + config.FEE_RATE * price * (1 - price)
        n = int(min(math.floor(budget / per), math.floor(depth or 0)))
        while n > 0 and n * price + fee(n, price) > budget + 1e-9:
            n -= 1
        if n < 1:
            return None, "no depth" if not depth else "no cash"
        tid = self.next_id()
        row = {"trade_id": tid, "opened_utc": iso(now), "bot": bot, "ticker": snap["ticker"],
               "category": snap.get("category", ""), "side": side, "price": price,
               "contracts": n, "cost": round(n * price, 2), "fee": fee(n, price),
               "forecast_prob": prob, "status": "open", "result": "", "payout": "",
               "pnl": "", "settled_utc": ""}
        self.new.append(row)
        return tid, f"bought {n} {side} at {price:.2f}"

    def flush(self, ledger):
        head = config.TABS["Trades"]
        ledger.append("Trades", [[cell(r[h]) for h in head] for r in self.new])
        self.rows.extend(self.new)
        self.new = []


def choose_side(prob, snap):
    """The trade rule: buy the side whose ask the forecast beats by at least EDGE."""
    ya, na = snap.get("yes_ask"), snap.get("no_ask")
    e_yes = prob - ya if ya is not None else -1
    e_no = (1 - prob) - na if na is not None else -1
    if max(e_yes, e_no) < config.EDGE:
        return None
    if e_yes >= e_no:
        return "YES", ya, snap.get("yes_ask_depth")
    return "NO", na, snap.get("no_ask_depth")


# ---------- forecasts ----------

def process_forecasts(ledger, snaps, now, book):
    """Stamp each new forecast row with the time this script first saw it and the market mid then.

    The stamp, not the bot's own timestamp, is the forecast time, so nothing can be back-dated.
    """
    active = active_slate(ledger, now)
    stats = {}
    for bot in config.FORECASTERS:
        tab = f"F_{bot}"
        updates, n_new = [], 0
        for r in ledger.records(tab):
            if str(r.get("seen_utc", "")).strip():
                continue
            ticker = str(r.get("ticker", "")).strip().upper()
            prob = parse_prob(r.get("prob_yes"))
            if prob is None:
                check, mid_v, tid = "bad prob_yes (use 0.01 to 0.99)", "", ""
            elif ticker not in active:
                check, mid_v, tid = "not an active slate market", "", ""
            elif ticker not in snaps:
                continue  # active but no price this tick; try again next tick
            else:
                snap = snaps[ticker]
                mid_v = cell(snap.get("mid"))
                tid = ""
                if book.holds(bot, ticker):
                    check = "ok, already holding"
                else:
                    pick = choose_side(prob, snap)
                    if pick is None:
                        check = "ok, no edge"
                    else:
                        side, price, depth = pick
                        tid, note = book.open_position(now, bot, snap, side, price, depth, prob)
                        check = f"ok, {note}"
                        tid = tid or ""
            n_new += 1
            row = r["_row"]
            updates += [(row, "seen_utc", iso(now)), (row, "mid_at_seen", mid_v),
                        (row, "check", check), (row, "trade_id", tid)]
        ledger.update(tab, updates)
        stats[bot] = n_new
    return stats


def baselines(ledger, snaps, now, book):
    """Market and Longshot Fader each forecast once per market, at the first snapshot after slating."""
    done = {(r.get("bot"), r.get("ticker")) for r in ledger.records("F_Baselines")}
    rows = []
    for t, s in snaps.items():
        m = s.get("mid")
        if m is None:
            continue
        if ("Market", t) not in done:
            p = clamp_prob(m)
            rows.append(["Market", iso(now), t, p, "entry", "market mid at slate entry",
                         iso(now), cell(m), "ok, never trades", ""])
        if ("Longshot Fader", t) not in done:
            tid, check = "", "ok, not a longshot"
            if m < config.LONGSHOT:
                p = clamp_prob(m * config.FADE_SHADE)
                if not book.holds("Longshot Fader", t):
                    tid, note = book.open_position(now, "Longshot Fader", s, "NO", s.get("no_ask"),
                                                   s.get("no_ask_depth"), p)
                    check, tid = f"ok, {note}", tid or ""
            elif m > 1 - config.LONGSHOT:
                p = clamp_prob(1 - (1 - m) * config.FADE_SHADE)
                if not book.holds("Longshot Fader", t):
                    tid, note = book.open_position(now, "Longshot Fader", s, "YES", s.get("yes_ask"),
                                                   s.get("yes_ask_depth"), p)
                    check, tid = f"ok, {note}", tid or ""
            else:
                p = clamp_prob(m)
            rows.append(["Longshot Fader", iso(now), t, p, "entry", "fade longshots under 15c",
                         iso(now), cell(m), check, tid])
    ledger.append("F_Baselines", rows)
    return len(rows)


# ---------- settlement ----------

def settle(kalshi, ledger, now):
    """Record results for closed slate markets and settle their paper trades."""
    results = {r["ticker"]: r for r in ledger.records("Results")}
    seen, new_rows = set(), []
    for r in ledger.records("Slate"):
        t = (r.get("ticker") or "").strip().upper()
        close = parse_time(r.get("close_time_utc"))
        if not t or t in results or t in seen or not close or close > now:
            continue
        seen.add(t)
        m = kalshi.market(t)
        if not m:
            continue
        res = (m.get("result") or "").strip().lower()
        status = (m.get("status") or "").lower()
        if res in ("yes", "no"):
            outcome = res
        elif status in ("settled", "finalized") and res:
            outcome = "void"
        else:
            continue  # closed but not determined yet
        settled = parse_time(m.get("settlement_ts")) or now
        row = [t, r.get("category", ""), r.get("title", ""), iso(close), outcome, iso(settled)]
        new_rows.append(row)
        results[t] = dict(zip(config.TABS["Results"], row))
    ledger.append("Results", new_rows)

    updates = []
    for tr in ledger.records("Trades"):
        if tr.get("status") != "open" or tr.get("ticker") not in results:
            continue
        outcome = results[tr["ticker"]]["result"]
        n, cost, f = to_float(tr["contracts"], 0), to_float(tr["cost"], 0), to_float(tr["fee"], 0)
        if outcome == "void":
            payout, pnl = cost + f, 0.0
        else:
            payout = n * 1.0 if tr["side"].lower() == outcome else 0.0
            pnl = payout - cost - f
        row = tr["_row"]
        updates += [(row, "status", "settled"), (row, "result", outcome),
                    (row, "payout", round(payout, 2)), (row, "pnl", round(pnl, 2)),
                    (row, "settled_utc", results[tr["ticker"]]["settled_utc"])]
    ledger.update("Trades", updates)
    return len(new_rows)

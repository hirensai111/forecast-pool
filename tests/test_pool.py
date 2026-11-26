"""End-to-end test on fake Kalshi data: candidates -> slate -> forecasts -> paper trades -> settle -> score."""
from datetime import timedelta

import pytest

from pool import collector, paper_trader, scorer
from pool.kalshi import parse_orderbook
from pool.ledger import MemoryLedger
from pool.util import fee, iso, parse_prob, utcnow

NOW = utcnow()


def mk(ticker, close_days, yb, ya, status="active", result="", mtype="binary"):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "market_type": mtype,
            "status": status, "close_time": iso(NOW + timedelta(days=close_days)),
            "yes_bid_dollars": f"{yb:.4f}", "yes_ask_dollars": f"{ya:.4f}",
            "no_bid_dollars": f"{1 - ya:.4f}", "no_ask_dollars": f"{1 - yb:.4f}",
            "last_price_dollars": f"{(yb + ya) / 2:.4f}", "volume_24h_fp": "500.00",
            "open_interest_fp": "900.00", "title": ticker, "yes_sub_title": "Yes",
            "rules_primary": f"Resolves YES if {ticker} happens.", "result": result}


class FakeKalshi:
    def __init__(self):
        self.m = {
            "ECON-A": mk("ECON-A", 2, 0.39, 0.41),
            "WX-B": mk("WX-B", 3, 0.07, 0.09),
        }
        self.events = [
            {"event_ticker": "ECON", "series_ticker": "KXECON", "category": "Economics",
             "title": "Econ event", "markets": [self.m["ECON-A"], mk("ECON-FAR", 30, .4, .42)]},
            {"event_ticker": "WX", "series_ticker": "KXWX", "category": "Climate and Weather",
             "title": "Weather event", "markets": [self.m["WX-B"]]},
            {"event_ticker": "FIN", "category": "Financials", "title": "Excluded",
             "markets": [mk("FIN-C", 2, .4, .42)]},
            {"event_ticker": "SPT", "category": "Sports", "title": "Combo",
             "markets": [mk("SPT-D", 2, .4, .42, mtype="scalar")]},
        ]

    def open_events(self):
        return self.events

    def markets(self, tickers):
        return {t: self.m[t] for t in tickers if t in self.m}

    def market(self, t):
        return self.m.get(t)

    def orderbook(self, t):
        m = self.m[t]
        yb, nb = float(m["yes_bid_dollars"]), float(m["no_bid_dollars"])
        return parse_orderbook({"orderbook_fp": {
            "yes_dollars": [[f"{yb - .01:.4f}", "300.00"], [f"{yb:.4f}", "100.00"]],
            "no_dollars": [[f"{nb - .01:.4f}", "300.00"], [f"{nb:.4f}", "100.00"]]}})


def test_fee_matches_kalshi_schedule():
    assert fee(100, 0.55) == 1.74      # Kalshi's own worked example
    assert fee(100, 0.10) == 0.63
    assert fee(1, 0.50) == 0.02
    assert fee(100, 0.50) == 1.75


def test_parse_prob():
    assert parse_prob("0.62") == 0.62
    assert parse_prob("62%") == 0.62
    assert parse_prob("maybe") is None
    assert parse_prob("1.0") is None and parse_prob("0") is None


def test_orderbook_asks_come_from_opposite_bids():
    ob = parse_orderbook({"orderbook_fp": {"yes_dollars": [["0.3000", "100.00"]],
                                           "no_dollars": [["0.6500", "40.00"]]}})
    assert ob["yes_ask"] == 0.35 and ob["yes_ask_depth"] == 40
    assert ob["no_ask"] == 0.70 and ob["no_ask_depth"] == 100


def test_full_cycle():
    k, led = FakeKalshi(), MemoryLedger()

    n = collector.refresh_candidates(k, led, NOW)
    tickers = {r["ticker"] for r in led.records("Candidates")}
    assert n == 2 and tickers == {"ECON-A", "WX-B"}     # far-dated, Financials, scalar all dropped

    for r in led.records("Candidates"):
        led.append("Slate", [[NOW.date().isoformat(), r["ticker"], r["category"], r["title"],
                              r["outcome"], r["close_time_utc"], r["rules"], "test"]])

    # Bots append forecasts (first five columns only).
    led.append("F_Newshound", [[iso(NOW), "ECON-A", "0.55", "evening", "news"]])
    led.append("F_Historian", [[iso(NOW), "ECON-A", "0.40", "evening", "base rate"]])
    led.append("F_Quant", [[iso(NOW), "econ-a", "62%", "evening", "consensus"]])
    led.append("F_Contrarian", [[iso(NOW), "ECON-A", "maybe", "evening", "?"]])
    led.append("F_Ensemble", [[iso(NOW), "NOT-ON-SLATE", "0.5", "evening", "avg"]])

    book = paper_trader.Book(led)
    snaps = collector.snapshot(k, led, NOW)
    assert snaps["ECON-A"]["yes_ask"] == 0.41 and snaps["ECON-A"]["mid"] == 0.40
    assert len(led.records("Latest")) == 2

    paper_trader.process_forecasts(led, snaps, NOW, book)
    paper_trader.baselines(led, snaps, NOW, book)
    book.flush(led)

    checks = {b: led.records(f"F_{b}")[0]["check"] for b in
              ("Newshound", "Historian", "Quant", "Contrarian", "Ensemble")}
    # 0.55 leaves the 5-point edge up to 0.50, so it buys all 100 at 0.41 and then 16 more at 0.42.
    assert checks["Newshound"] == "ok, bought 116 YES at 0.41 over 2 prices up to 0.42"
    assert checks["Historian"] == "ok, no edge"
    assert checks["Quant"].startswith("ok, bought")
    assert checks["Contrarian"].startswith("bad prob_yes")
    assert checks["Ensemble"] == "not an active slate market"

    trades = led.records("Trades")
    news = next(t for t in trades if t["bot"] == "Newshound")
    assert news["contracts"] == 116 and news["cost"] == 47.72 and news["fee"] == 1.98
    fader = next(t for t in trades if t["bot"] == "Longshot Fader")
    assert fader["side"] == "NO" and fader["ticker"] == "WX-B"
    assert all(float(t["cost"]) + float(t["fee"]) <= 50 for t in trades)
    assert not any(t["bot"] == "Market" for t in trades)

    # A second tick must not re-stamp rows or open duplicate positions.
    book2 = paper_trader.Book(led)
    paper_trader.process_forecasts(led, snaps, NOW, book2)
    paper_trader.baselines(led, snaps, NOW, book2)
    assert book2.new == []

    # Markets close and settle: ECON-A yes, WX-B no.
    later = NOW + timedelta(days=4)
    k.m["ECON-A"].update(status="finalized", result="yes")
    k.m["WX-B"].update(status="finalized", result="no")
    assert paper_trader.settle(k, led, later) == 2
    news = next(t for t in led.records("Trades") if t["bot"] == "Newshound")
    assert news["status"] == "settled" and news["pnl"] == pytest.approx(66.30)

    board = {r[1]: r for r in scorer.score(led, later)}
    # Newshound said 0.55 on a YES market priced 0.40: better than the market.
    assert board["Newshound"][6] < 0
    assert board["Historian"][6] == pytest.approx(0.0)
    assert board["Market"][6] == 0.0
    assert board["Newshound"][11] == pytest.approx(66.30)
    assert led.records("Calibration") and led.records("ByCategory")


def test_walks_the_book_only_while_the_edge_holds():
    led = MemoryLedger()
    snap = {"ticker": "X", "category": "sports"}
    levels = [(0.20, 5), (0.22, 10), (0.30, 500)]
    # Forecast 0.30: limit 0.25, so 0.20 and 0.22 fill and 0.30 is skipped.
    book = paper_trader.Book(led)
    tid, note = book.open_position(NOW, "Quant", snap, "YES", 0.20, 5, 0.30, levels, 0.25)
    t = book.new[0]
    assert t["contracts"] == 15 and t["cost"] == 3.20 and note.endswith("over 2 prices up to 0.22")
    # Forecast 0.40: limit 0.35, so it reaches 0.30 and stops at the $50 cap.
    book = paper_trader.Book(led)
    book.open_position(NOW, "Quant", snap, "YES", 0.20, 5, 0.40, levels, 0.35)
    t = book.new[0]
    assert t["cost"] + t["fee"] <= 50 and t["cost"] + t["fee"] > 49 and t["contracts"] > 150
    # Without levels it buys only what rests at the best ask, as before.
    book = paper_trader.Book(led)
    book.open_position(NOW, "Quant", snap, "YES", 0.20, 5, 0.40)
    assert book.new[0]["contracts"] == 5


def test_orderbook_ladder():
    ob = parse_orderbook({"orderbook_fp": {"yes_dollars": [["0.3000", "100.00"], ["0.2900", "50.00"]],
                                           "no_dollars": [["0.6500", "40.00"], ["0.6400", "70.00"]]}})
    assert ob["yes_ask_levels"] == [(0.35, 40.0), (0.36, 70.0)]
    assert ob["no_ask_levels"] == [(0.70, 100.0), (0.71, 50.0)]

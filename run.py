"""Forecast Pool command line.

    python run.py preview      check Kalshi data works, no Google setup needed
    python run.py init         create the ledger tabs and headers
    python run.py candidates   refresh the Candidates tab for Curator
    python run.py tick         snapshot prices, stamp forecasts, paper-trade, settle (every 15 min)
    python run.py score        rewrite Scoreboard, ByCategory and Calibration (daily)

Reads Kalshi's public market data only. No Kalshi account, no orders, no real money.
"""
import sys

from pool import collector, paper_trader, scorer
from pool.kalshi import Kalshi
from pool.ledger import SheetsLedger
from pool.util import utcnow


def tick(kalshi, ledger, now):
    snaps = collector.snapshot(kalshi, ledger, now)
    book = paper_trader.Book(ledger)
    stamped = paper_trader.process_forecasts(ledger, snaps, now, book)
    n_base = paper_trader.baselines(ledger, snaps, now, book)
    n_trades = len(book.new)
    book.flush(ledger)
    n_settled = paper_trader.settle(kalshi, ledger, now)
    print(f"tick: {len(snaps)} markets snapshotted, forecasts stamped {stamped}, "
          f"{n_base} baseline rows, {n_trades} paper trades, {n_settled} markets settled")


def preview(now):
    """Try the Kalshi side with no Google setup: fetch candidates and one order book, print them."""
    from collections import Counter

    from pool.ledger import MemoryLedger

    k, led = Kalshi(), MemoryLedger()
    n = collector.refresh_candidates(k, led, now)
    rows = led.records("Candidates")
    print(f"{n} candidate markets: {dict(Counter(r['category'] for r in rows))}")
    for r in rows[:5]:
        print(f"  {r['category']:<13} {r['ticker']:<34} yes_ask={r['yes_ask']}  {r['title'][:50]}")
    if rows:
        print(f"order book for {rows[0]['ticker']}: {k.orderbook(rows[0]['ticker'])}")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "tick"
    now = utcnow()
    if cmd == "preview":
        return preview(now)
    ledger = SheetsLedger()
    if cmd == "init":
        ledger.ensure_tabs()
        print("ledger tabs ready")
    elif cmd == "candidates":
        print(f"candidates: {collector.refresh_candidates(Kalshi(), ledger, now)} markets")
    elif cmd == "tick":
        tick(Kalshi(), ledger, now)
    elif cmd == "score":
        board = scorer.score(ledger, now)
        for row in board:
            print(f"  {row[1]:<15} markets={row[2]:<4} brier_vs_market={row[6]}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)

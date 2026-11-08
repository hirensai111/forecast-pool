"""Settings for the Forecast Pool. Change numbers here, not in the code."""
import os

# Kalshi public market data (read-only, no account, no orders).
KALSHI_BASE = os.environ.get("KALSHI_BASE", "https://api.elections.kalshi.com/trade-api/v2")
REQUEST_PAUSE_S = 0.15          # gap between Kalshi requests, to stay well under rate limits

# Google Sheet ledger.
SHEET_ID = os.environ.get("POOL_SHEET_ID", "")
SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Paper money rules.
BANKROLL = 1000.0               # virtual dollars per bot
MAX_PER_MARKET = 50.0           # most a bot may put into one market (cost + fee)
EDGE = 0.05                     # trade only when the bot's probability beats the ask by 5 points
FEE_RATE = 0.07                 # Kalshi general taker fee: round_up(0.07 * C * P * (1 - P))

# Baselines.
LONGSHOT = 0.15                 # Longshot Fader fades any side priced under 15 cents
FADE_SHADE = 0.6                # ...and believes longshots win 40% less often than priced

# Candidate markets for Curator.
CANDIDATE_MAX_DAYS = 14         # closes within 14 days (Curator still requires at least 1 day)
CANDIDATE_MIN_PRICE = 0.02
CANDIDATE_MAX_PRICE = 0.98
CANDIDATES_PER_CATEGORY = 60    # keep the tab readable: top markets by 24h volume
RULES_MAX_CHARS = 600

# Kalshi category -> pool category. Anything not listed is ignored.
CATEGORY_MAP = {
    "economics": "economics",
    "financials": None,
    "climate and weather": "weather",
    "weather": "weather",
    "politics": "politics",
    "elections": "politics",
    "entertainment": "entertainment",
    "culture": "entertainment",
    "sports": "sports",
}

FORECASTERS = ["Newshound", "Historian", "Quant", "Contrarian", "Ensemble"]
BASELINES = ["Market", "Longshot Fader"]
ALL_BOTS = FORECASTERS + BASELINES

FORECAST_COLS = ["ts_utc", "ticker", "prob_yes", "round", "reason",
                 "seen_utc", "mid_at_seen", "check", "trade_id"]

TABS = {
    "Candidates": ["refreshed_utc", "ticker", "event_ticker", "category", "title", "outcome",
                   "close_time_utc", "yes_bid", "yes_ask", "last_price", "volume_24h",
                   "open_interest", "rules", "url"],
    "Slate": ["slate_date", "ticker", "category", "title", "outcome", "close_time_utc",
              "rules", "note"],
    "Latest": ["updated_utc", "ticker", "title", "yes_bid", "yes_ask", "mid", "close_time_utc"],
    **{f"F_{b}": FORECAST_COLS for b in FORECASTERS},
    "F_Baselines": ["bot"] + FORECAST_COLS,
    "Snapshots": ["ts_utc", "ticker", "status", "yes_bid", "yes_ask", "no_bid", "no_ask",
                  "last_price", "mid", "yes_ask_depth", "no_ask_depth", "volume_24h",
                  "open_interest"],
    "Trades": ["trade_id", "opened_utc", "bot", "ticker", "category", "side", "price",
               "contracts", "cost", "fee", "forecast_prob", "status", "result", "payout",
               "pnl", "settled_utc"],
    "Results": ["ticker", "category", "title", "close_time_utc", "result", "settled_utc"],
    "Scoreboard": ["updated_utc", "bot", "markets_scored", "forecasts", "brier",
                   "market_brier", "brier_vs_market", "log_loss", "trades_settled",
                   "trades_open", "win_rate", "pnl", "roi", "ready"],
    "ByCategory": ["updated_utc", "bot", "category", "markets_scored", "brier",
                   "market_brier", "brier_vs_market", "trades_settled", "pnl"],
    "Calibration": ["updated_utc", "bot", "bucket", "forecasts", "avg_forecast", "hit_rate"],
}

READY_AT = 100                  # forecasts on settled markets before a bot is judged

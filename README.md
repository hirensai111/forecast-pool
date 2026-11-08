# Forecast Pool scripts

The mechanical half of the Forecast Pool: data collection, paper trades, settlement and scoring.
The six Grok bots only read the Google Sheet and append rows; these scripts do everything else.

Educational and paper-only. The scripts read Kalshi's **public, read-only** market data. There is
no Kalshi account, no login, no order placement and no real money anywhere. Skim Kalshi's API
terms before you start.

## What each file does

| File | Job |
| --- | --- |
| `pool/collector.py` | Refreshes **Candidates** for Curator; snapshots prices and order-book depth for the active slate into **Snapshots** and **Latest** |
| `pool/paper_trader.py` | Stamps each new forecast with the time it was first seen and the market mid then; applies the trade rule; runs the two baselines; settles closed markets |
| `pool/scorer.py` | Writes **Scoreboard**, **ByCategory** and **Calibration** |
| `pool/config.py` | Every number you might want to change: bankroll, $50 cap, 5-point edge, fee rate, categories |
| `run.py` | Command line: `preview`, `init`, `candidates`, `tick`, `score` |
| `.github/workflows/pool.yml` | Runs `tick` every 15 min, `candidates` at 18:15 IST, `score` at 08:45 IST |
| `forecast_pool_ledger.xlsx` | Ledger template with every tab and header |

## The rules the scripts enforce

- **Forecast time = first seen.** A bot's own timestamp is ignored; the script stamps `seen_utc` and
  `mid_at_seen` the first tick it sees a row, so nothing can be back-dated.
- **Trade rule.** Buy YES if `prob_yes - yes_ask >= 0.05`; buy NO if `(1 - prob_yes) - no_ask >= 0.05`.
  One position per bot per market, held to settlement.
- **Fills.** At the ask, only up to the size resting at the best level, plus Kalshi's taker fee
  `round_up(0.07 x C x P x (1 - P))`. Total cost + fee per market is capped at $50, and at the bot's cash.
- **Baselines.** *Market* forecasts the mid at slate entry and never trades. *Longshot Fader* buys the
  other side of anything priced under 15 cents.
- **Scoring.** Brier score per market (a bot's rows on one market are averaged first), compared with the
  market mid at the same moments. `brier_vs_market` below 0 means better than the crowd.
  A bot is `ready` to judge after 100 forecasts on settled markets.

## Setup (about 30 minutes)

1. **Try the data first.** On any computer with Python 3.11+:
   `pip install -r requirements.txt` then `python run.py preview`.
   It prints candidate markets per category and one order book. If this fails from where you are,
   the GitHub runner in step 4 still works, since it runs on GitHub's servers.
2. **The sheet.** In the desk-only Google account, create a Google Sheet and import
   `forecast_pool_ledger.xlsx` (File > Import > Replace spreadsheet). Copy the sheet ID from its URL
   (the part between `/d/` and `/edit`).
3. **A service account for the scripts.** In Google Cloud Console (same desk-only account): create a
   project, enable the **Google Sheets API**, create a **service account**, and add a **JSON key**.
   Share the sheet with the service account's email as **Editor**. Keep the JSON file private.
4. **GitHub.** Put this folder in a new repository.
   - Public repo: scheduled runs are free. Private repo: the free plan includes 2,000 minutes a month,
     so change the first cron line to `*/30 * * * *`.
   - Settings > Secrets and variables > Actions: add `POOL_SHEET_ID` (the ID) and
     `GOOGLE_SERVICE_ACCOUNT_JSON` (the whole JSON file's contents).
5. **First runs.** Actions > forecast-pool > Run workflow, in this order: `init`, `candidates`.
   Check the Candidates tab fills. From then on the schedule runs by itself.
6. **Bots.** Paste the six descriptions from the Forecast Pool doc into Grok Bot, give each the
   sheet link, and set the routines.

GitHub's scheduled runs can start a few minutes late at busy times; that only delays stamping, and
the stamp is what counts. GitHub also pauses schedules in a public repo after 60 days with no commits.

## Tests

`python -m pytest -q` runs a full cycle on fake Kalshi data: candidates, slate, forecasts,
paper trades, fees, settlement and scoring.

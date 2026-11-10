# backtrader-runner

Runs [backtrader](https://www.backtrader.com/) backtests on GitHub Actions, where the
commands to execute live in a repository **Actions variable** — not in code.

> **Note on upstream maintenance:** Upstream backtrader is effectively unmaintained (last upstream commit April 2023); the library still installs and runs, which this pilot verifies.

## The pattern (one repo per tool)

1. **Edit the commands**: repo *Settings → Secrets and variables → Actions →
   Variables* → set the `COMMANDS` variable to whatever shell commands this
   run should execute (multi-line works). The same can be done through the
   GitHub API (`PUT /repos/{owner}/{repo}/actions/variables/COMMANDS`).
2. **Trigger manually**: *Actions* tab → “Run analysis” → *Run workflow*
   (or `POST /repos/{owner}/{repo}/actions/workflows/run.yml/dispatches`).
   The workflow has **no other triggers** — it runs only when dispatched.
3. **Collect results**: the workflow uploads everything under `results/` as
   the `results` build artifact (`if: always()`, so partial results survive
   a failing step). Download it from the run page or via the API.

The workflow itself is generic: checkout → Python 3.11 → `pip install -r
requirements.txt` → run `${{ vars.COMMANDS }}` → upload `results/`.
To run a different analysis, change the variable — not the workflow.

## Multi-market by design

Nothing in the workflow or the runner pattern is tied to one exchange.
Scripts take the **ticker symbol and analysis parameters as inputs** (CLI
args and/or the `COMMANDS` variable), so the same repo can analyse an EGX
stock today and a US stock (e.g. markets available through Nsave or Alpaca)
tomorrow — only the inputs change.

## What the tool is

[backtrader](https://www.backtrader.com/) is a Python backtesting framework
for trading strategies: you define a strategy (indicators, buy/sell logic,
sizing), feed it OHLC data, and it simulates a broker, orders and a portfolio
over historical bars, reporting the final value and trade statistics.

Price data in this repo comes from Yahoo's chart API called **directly**
with `requests` — never yfinance. Endpoint:
`https://query1.finance.yahoo.com/v8/finance/chart/<ticker>?period1=<epoch>&period2=<epoch>&interval=1d`
with a browser User-Agent; the response is parsed into a pandas OHLC
DataFrame and fed to backtrader via `bt.feeds.PandasData`.

## Pilot: AAPL SMA-cross backtest

Pilot inputs (defaults in `scripts/backtest.py`, overridable via CLI args):

- Ticker: `AAPL` (positional arg, or `--ticker`)
- History: last ~3 years of daily chart-API data (`--years 3`)
- Starting cash: `100000` (`--cash`)
- Strategy: simple SMA-cross — buy when close crosses above SMA20,
  sell/close when it crosses below SMA20 (`--sma-period 20`); stake ~95% of cash

Pilot `COMMANDS` value:

```sh
mkdir -p results
python scripts/backtest.py 2>&1 | tee results/run.log
```

The script prints and writes `results/stats.json` with: start value,
final value, total return %, number of completed trades, data rows and
date range.

# Apex Chronos MASTER bot

Built from `APEX_CHRONOS_MASTER_STRATEGY.md` and the code in `../backtest/`. Every rule and number in
`apex_master_bot/config.py` is copied from the backtest scripts, not from the prose in the strategy document
(the two differ in places, see "Where the document and the tested code disagree").

**The bot sends paper alerts only. It never places an order.**

## What it does (exactly as tested)
- Universe SPY, QQQ, IWM. 5-minute bars, 09:30-15:55 ET. Modules **P1C** (ORB-15 trap reject, primary) and **P2** (midday range-wall pin, fallback). P1A, P1B, P3 are not built.
- Each module fires at most once per ticker per day. At most one trade per day.
- Rank: P1C before P2, then the candidate whose RVOL is closest to 1.00. RVOL = cumulative volume vs. the mean of the prior 20 sessions at the same 5-minute slot.
- Entry: open of the bar after the signal bar. `R = max(0.9 x ATR14, close x 0.0008)`.
- Exit (profile `reliability`, the adopted one): target +1.2R on a bar high/low touch, stop -1R on a bar **close** only, time exit after 20 bars (100 min). 0.15R cost on every trade. Profile `runner` uses +2.5R.
- VIX gate: no trade if the prior-day VIX close is 25 or higher (`master_config.json`). It never fires in the tested sample, so it does not change any tested result (checked by a test).

## Proof it matches the backtest
```
cd apex_master_bot
python3 -m apex_master_bot replay --data ../data --published ../results/MASTER_trades_tp1.2.csv
python3 -m apex_master_bot replay --data ../data --profile runner --published ../results/RUNNER_trades_tp2.5.csv
python3 -m unittest discover -s tests -v
```
Both profiles reproduce all 57 published trades: same ticker, module, direction, entry minute and R (largest difference 4e-16).
Reliability: win 70.2%, mean +0.306R, PF 1.74, max drawdown -3.5R. Runner: win 59.6%, mean +0.601R, PF 2.14, max drawdown -6.2R.

## The catch: the tested pick cannot be made live
The published results choose each day's trade **after seeing all of that day's candidates** (`make_final.py` sorts the whole day by
module priority and |RVOL - 1| and keeps the first). On 23 of 57 days that trade is not the first one to fire. A live bot cannot know
at 10:05 that a better-ranked candidate will appear at 10:40. So `replay` can run the tested pick exactly, and `live` has to use a causal rule.

Live rule = **first_fire**: take the first P1C/P2 candidate that completes (ties on the same bar use the tested ranking). Same bars, same data, same costs:

| Pick rule (57 days, same candidates) | Win | Mean R | PF | Max DD |
|---|---|---|---|---|
| Tested (looks at the whole day) - reliability | 70.2% | +0.31 | 1.74 | -3.5R |
| **first_fire (what live can do) - reliability** | 57.9% | -0.02 | 0.97 | -12.8R |
| Tested - runner | 59.6% | +0.60 | 2.14 | -6.2R |
| **first_fire - runner** | 47.4% | +0.17 | 1.24 | -15.9R |
| Wait until the P1C window closes (11:14), then take the tested pick - reliability | 43.6% | -0.26 | 0.61 | n/a |

Reproduce the first_fire rows with `--selection first_fire`. So on this sample the edge shown in the strategy document comes from the
hindsight pick, not from the signals. The live bot is faithful to the signals and exits, and the forward test in section 9 of the
strategy document is what decides whether it works. Treat `live` as a data-collection tool until that test says otherwise.

## Where the document and the tested code disagree
The strategy document describes more than the backtest ran. These are **not** in the bot's default behaviour because they were never tested:
Quality Score and its 60 floor, the RVOL > 1.65 veto, the SPY-slope veto, the P1B veto, IBS and fear-gauge bonuses, the full Regime Engine v4 downgrades
(only the VIX leg is built), and the options-spread structure. `master_select.py` in the backtest folder claims to be "the exact rule set backtested" but
it is not: `make_final.py` is what produced the numbers. The RVOL > 1.65 veto can be turned on with `veto_rvol_above` in `config.py`; on this sample it leaves the result unchanged.

Also: results are in **underlying R-multiples on 5-minute bars**, not option P&L. The alert gives stop and target levels on the ETF, because that is what was measured.

## Run it live
```
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL=...      # optional
export ACCOUNT_SIZE=25000           # optional, only used to print shares per 1R
./run_today.sh                      # start at 09:20 ET; a crontab line is in the script header
```
- Risk rules from the document, live only: 0.50% of account at risk per trade (0.25% when the prior VIX is 20-25), no trading after a -3R week (reads `ledger/trades.csv`), no trade on dates in `event_days.txt` (starts empty) or on the half-days 2026-11-27 and 2026-12-24.
- Signals are only acted on within one bar of firing; later ones are logged as MISSED and not chased.
- Everything is logged: `ledger/candidates.csv` (every signal), `ledger/trades.csv` (closed trades), `state/<date>.json` (resume after a restart), `logs/alerts.log`.
- Dry run on any saved day: `python3 -m apex_master_bot live --simulate-date 2026-10-29 --data ../data --state-dir /tmp/x --ledger-dir /tmp/x --poll 60`.

## What was not tested
- The Yahoo live feed (`YahooProvider`): the sandbox this was built in could not install or reach `yfinance`. Run one dry day and compare its bars to your broker before trusting it. Yahoo's 5-minute bars can lag, and entry latency matters (the Apex docs put 1 minute of delay at about -19% of the edge).
- Real fills and spreads. The 0.15R cost is a proxy; the document's own stress test shows the edge is gone at about +0.30R extra.

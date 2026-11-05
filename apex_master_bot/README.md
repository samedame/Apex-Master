# Apex Chronos MASTER bot

Built from `APEX_CHRONOS_MASTER_STRATEGY.md` and the code in `../backtest/`. Every rule and number in
`apex_master_bot/config.py` is copied from the backtest scripts, not from the prose in the strategy document
(the two differ in places, see "Where the document and the tested code disagree").

**The bot sends paper alerts only. It never places an order.**

> **Audit note (2026-11-04).** The v1 pipeline below replays the tested rules exactly, but the published 57-trade numbers rest on a hindsight pick; the live first-signal rule is about flat (-0.020R reliability, +0.165R runner). v1 is unchanged. The v2 candidate that survived the audit runs beside it as a separate alert-only module: see "Master v2 alerts" below and `../research/master_v2/README.md`.

## What it does (exactly as tested)
- Universe SPY, QQQ, IWM. 5-minute bars, 09:30-15:55 ET. Modules **P1C** (ORB-15 trap reject, primary) and **P2** (midday range-wall pin, fallback). P1A, P1B, P3 are not built.
- Each module fires at most once per ticker per day. At most one trade per day.
- Rank: P1C before P2, then the candidate whose RVOL is closest to 1.00. RVOL = cumulative volume vs. the mean of the prior 20 sessions at the same 5-minute slot.
- Entry: open of the bar after the signal bar. `R = max(0.9 x ATR14, close x 0.0008)`.
- Exit (profile `reliability`, the adopted one): target +1.2R on a bar high/low touch, stop -1R on a bar **close** only, time exit after 20 bars (100 min). 0.15R cost on every trade. Profile `runner` uses +2.5R.
- VIX gate: no trade if the prior-day VIX close is 25 or higher (`master_config.json`). It never fires in the tested sample, so it does not change any tested result (checked by a test).

## Master v2 alerts (added 2026-11-04, paper alerts only)
Rule: previous VIX close >= 20 and previous-day IBS < 0.10 for SPY, then QQQ, then IWM (first one wins). Buy at the open, sell at the close, at most one trade a day. Evidence and limits: `../research/master_v2/README.md` (+18.19 bp per trade over 30 years, about 24 trades a year, plan on about half of that, unproven out of sample, option P&L unverified). **It sends no orders.**

- **When:** a pre-open step at the start of `master-session` (the 09:20 ET run) calls `v2-check`. It uses only the previous session's bars, so there is nothing to watch intraday. A v2 failure never blocks the v1 session.
- **Alerts:** Discord only when a trade qualifies (ticker, IBS, VIX, sigma, candidate option strikes and their empirical fair values). No-trade days are silent. Any data problem sends a loud `NO DECISION` message with the manual rule. Fridays post a one-line weekly status as a heartbeat.
- **Data guards:** the previous-session bar must exist for SPY, QQQ, IWM and VIX (no stale data). VIX is cross-checked against FRED VIXCLS; if the two disagree across the 20 gate there is no decision.
- **Ledger:** `ledger/v2_checks.csv` (every check), `ledger/v2_trades.csv` (paper trades, open to close, net of 2 bp), `state/v2/<date>.json`. Each morning the check first settles earlier signal days from the daily bar, then decides.
- **Forward-test rules built in:** an alert says PAUSE AND REVIEW if cumulative net return falls below -1,600 bp, and RETIRE if the mean is <= 0 at 40 trades. Do not edit the rule during the test.

```
python3 -m apex_master_bot v2-check --no-notify                       # decide for today (Yahoo + FRED), print only
python3 -m apex_master_bot v2-check --date 2026-11-05 --no-notify     # a specific session
python3 -m apex_master_bot v2-status                                  # forward-test summary
python3 -m apex_master_bot v2-replay --data ../research/master_v2/data --published ../research/master_v2/results/master_v2_trades.csv
```
`v2-replay` re-runs the same `decide()` the live check uses over 30 years of daily bars and matches all 734 published trades (a test asserts it). To run it outside GitHub Actions, schedule `v2-check` once each weekday at about 09:15 ET (it needs `pip install yfinance`).

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

## Run it live (hands-off)
```
pip install -r requirements.txt
touch .env      # then add lines such as:  DISCORD_WEBHOOK_URL=...   ACCOUNT_SIZE=25000   APEX_PROFILE=reliability
bash schedule/install_launchd.sh        # macOS: installs the bot starter + watchdog, every 5 minutes, survives reboots
```
Linux or other: use `schedule/crontab.example`. Both jobs run at any hour and read the New York clock themselves, so the machine's time zone does not matter.
The Mac has to be awake during market hours (09:30-16:00 ET = 07:30-14:00 Mountain); `caffeinate` is used while the bot runs, and the installer prints a `pmset` line to wake it.

- **Starter (`run_today.sh`, `ensure`)**: starts the bot on trading days from 09:10 ET if it is not already running. If the bot crashes, the next 5-minute call restarts it and the saved state resumes the session. A signal that fired while it was down is logged as MISSED, never chased.
- **Watchdog (`watchdog.sh`)**: silent on a healthy day. Alerts to Discord/console if the bot never started, stopped updating, the SPY bar feed is stuck, polls keep failing, or a trade was never closed in the ledger. Posts one line at the end of every day (traded +R / no trade and why) so a dead bot never looks like a quiet day. `market_holidays.txt` lists the closures it should ignore; extend it.
- **Heartbeat**: `state/heartbeat.json`, rewritten every poll.
- Risk rules from the document, live only: 0.50% of account at risk per trade (0.25% when the prior VIX is 20-25), no trading after a -3R week (reads `ledger/trades.csv`), no trade on dates in `event_days.txt` (starts empty) or on the half-days 2026-11-27 and 2026-12-24.
- Logs: `ledger/candidates.csv` (every signal), `ledger/trades.csv` (closed trades), `state/<date>.json`, `logs/alerts.log`.
- Dry run on any saved day: `python3 -m apex_master_bot live --simulate-date 2026-10-29 --data ../data --state-dir /tmp/x --ledger-dir /tmp/x --poll 60`.

## Run it in the cloud (GitHub Actions + Discord + Cloudflare scheduler)

One workflow, `.github/workflows/master-session.yml`, runs the whole day: it starts the live loop, then writes the end-of-day summary,
updates the scoreboard, commits `state/` and `ledger/` back to the repo, and posts to Discord. A day with no candidate by ~13:35 ET ends early.

1. **Discord webhook**: Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL.
2. **Repo secret**: GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret.
   Name = `DISCORD_WEBHOOK_URL`, Secret box = the URL. (Do not paste the URL into the Name box.)
3. Run the **discord-test** workflow (Actions tab -> discord-test -> Run workflow). A test message must appear in Discord.
4. Optional repo variables: `ACCOUNT_SIZE` (number), `APEX_PROFILE` (`reliability` or `runner`).
5. **Cloudflare**: add a job to the `open-scheduler` Worker that dispatches `master-session.yml` on `main` of `samedame/Apex-Master`
   at 09:20 ET, weekdays (Cron Triggers must use `MON-FRI` and cover UTC hours 13 and 14). The workflow takes the usual inputs
   `scheduled_for_et` and `trigger`. The Worker's `GH_PAT` must be allowed to dispatch workflows on this repo.
   A backup native cron (`25 13,14 * * 1-5`) is in the workflow and does nothing if the day is already done.
6. Run only ONE runner (Actions or the Mac launchd jobs), otherwise both write the same ledger.

Limits: state is committed at the end of the job, so a crash mid-day loses that day's state (the restart rescans and logs late signals as MISSED, it does not chase them).
The repo is public, so `state/` and `ledger/` are world-readable.

## Forward-test scoreboard
```
python3 -m apex_master_bot scoreboard            # prints the report and writes ledger/scoreboard.json
python3 -m apex_master_bot scoreboard --notify   # also posts a one-line summary to Discord (the crontab example does this on Fridays)
```
Scores `ledger/trades.csv` against the pass and kill bars registered in section 9 of the strategy document (win >= 60%, PF >= 1.30, mean >= +0.10R with bootstrap CI lower bound > -0.05R, max drawdown >= -8R, no more than 6 losses in a row; killed by PF < 0.90 or mean < -0.10R after 50 trades, real cost > 0.45R, or the gate blocking > 40% of days).
Each ledger row carries a fingerprint of the settings in force. If you change any rule (target, universe, gate, selection...), only trades under the new settings are counted, which is the document's "any change restarts the count". The verdict stays IN PROGRESS until both 100 trades and 182 days have passed, unless a kill criterion fires first. The real-cost test switches on once the `real_cost_R` column in the ledger is filled by quote logging.

## What was not tested
- The Yahoo live feed (`YahooProvider`): the sandbox this was built in could not install or reach `yfinance`. Run one dry day and compare its bars to your broker before trusting it. Yahoo's 5-minute bars can lag, and entry latency matters (the Apex docs put 1 minute of delay at about -19% of the edge).
- Real fills and spreads. The 0.15R cost is a proxy; the document's own stress test shows the edge is gone at about +0.30R extra.

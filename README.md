# Apex-Master

Apex Chronos MASTER: strategy document, the backtest that produced its numbers, and a paper-alert bot built to that backtest.

- `APEX_CHRONOS_MASTER_STRATEGY.md` / `.html` / `.pdf`: the strategy write-up
- `backtest/`, `data/`, `results/`, `master_config.json`: the backtest code, the 5-minute and daily bars it used, and its outputs (the backtest scripts still point at the author's original `/home/user/Apex_Master` paths)
- `research/master_v2/`: **2026-11-04 audit and Master v2.** Independent re-test of v1 (its published numbers rest on a hindsight pick; the live rule is flat) and the one rule that survived pre-registered testing: previous VIX >= 20 and IBS < 0.10, long SPY/QQQ/IWM open to close. Start with its README. Reproducible from the folder.
- `apex_master_bot/` also contains the **Master v2 alert module** (`v2-check`, paper alerts only, run pre-open by the `master-session` workflow). See the bot README.
- `apex_master_bot/`: the bot. Start with its README. It replays the tested pipeline exactly and runs live as paper alerts only.

Verify the bot against the published trade logs:

    cd apex_master_bot && python3 -m unittest discover -s tests -v

## Master v1 session turned off (2026-11-13)

`master-session` still runs the Master v2 pre-open check, its state save and the quote-snapshot dispatch. The v1 intraday session and its end-of-day scoreboard now need the repository variable `MASTER_V1_ENABLED=true`. Reason: the 2026-11-04 audit found v1's live rule flat (-0.020R, max drawdown past its -8R bar) and the day-long session billed 86-175 minutes a day on a private repo. Set the variable to bring v1 back.

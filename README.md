# Apex-Master

Apex Chronos MASTER: strategy document, the backtest that produced its numbers, and a paper-alert bot built to that backtest.

- `APEX_CHRONOS_MASTER_STRATEGY.md` / `.html` / `.pdf`: the strategy write-up
- `backtest/`, `data/`, `results/`, `master_config.json`: the backtest code, the 5-minute and daily bars it used, and its outputs (the backtest scripts still point at the author's original `/home/user/Apex_Master` paths)
- `apex_master_bot/`: the bot. Start with its README. It replays the tested pipeline exactly and runs live as paper alerts only.

Verify the bot against the published trade logs:

    cd apex_master_bot && python3 -m unittest discover -s tests -v

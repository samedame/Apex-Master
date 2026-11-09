# Apex-Master

Apex Chronos MASTER: strategy document, the backtest that produced its numbers, and a paper-alert bot built to that backtest.

- `APEX_CHRONOS_MASTER_STRATEGY.md` / `.html` / `.pdf`: the strategy write-up
- `backtest/`, `data/`, `results/`, `master_config.json`: the backtest code, the 5-minute and daily bars it used, and its outputs (the backtest scripts still point at the author's original `/home/user/Apex_Master` paths)
- `research/master_v2/`: **2026-11-04 audit and Master v2.** Independent re-test of v1 (its published numbers rest on a hindsight pick; the live rule is flat) and the one rule that survived pre-registered testing: previous VIX >= 20 and IBS < 0.10, long SPY/QQQ/IWM open to close. Start with its README. Reproducible from the folder.
- `apex_master_bot/` also contains the **Master v2 alert module** (`v2-check`, paper alerts only, run pre-open by the `master-session` workflow). See the bot README.
- `apex_master_bot/`: the bot. Start with its README. It replays the tested pipeline exactly and runs live as paper alerts only.

Verify the bot against the published trade logs:

    cd apex_master_bot && python3 -m unittest discover -s tests -v

## Paper research and account risk

The $1,500 paper research path retains the frozen v2 ETF benchmark and separates it from option quote diagnostics. The scheduled option snapshot authorizes zero contracts. See the [baseline audit](docs/BASELINE_AUDIT.md), [implementation status](docs/IMPLEMENTATION_CHANGELOG.md), [research results](docs/RESEARCH_VALIDATION.md), [risk configuration](docs/RISK_MANAGEMENT.md), and [option replay schema](docs/OPTIONS_EXECUTION.md).

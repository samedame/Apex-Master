# Implementation and validation status

| Area | Change | Evidence |
| --- | --- | --- |
| Baseline | Frozen v2 selection, original replay and cost; v1 replay retained. | 734 v2 dates and tickers match. Both v1 profiles still match 57 published picks. |
| Data | Exact prior-session VIX/ETF date checks, strict OHLC and gate validation, receipt timestamp, source and Git revision in new state. | Deterministic fixtures. Provider publication latency remains unverified. |
| Regime | Timestamped SPY/QQQ/IWM trend diagnostics, volatility classification, calendar input with an AS_OF cutoff, no calibrated probabilities. | Fixture-tested. Historical ETF comparisons only. |
| Options | Indicative Yahoo provenance, optional timestamped JSONL replay for four verticals, ETF share benchmark, natural and midpoint economics, exit and intrinsic scenarios. | Fixture-tested. No historical options execution result. |
| Risk | Centralized cash-backed sizing with one v2 entry, bounded daily and weekly risk, permissions and integrity gates. | Fixture-tested. No synchronized paper account state or approved strategy configured. |
| Alerts | Separate original signal, regime, indicative options economics and risk decision. End-of-day ETF benchmark and available simplified option marks. | Formatting and mock webhook fixtures. No actual Discord or brokerage operation exercised during development. |
| State | Atomic JSON and keyed CSV batches with advisory lock, same-ref v2 workflow serialization, existing CSV schemas retained. | Concurrent local checks and simulated partial-write recovery. Hosted scheduling and provider integration still need observation. |

The legacy v2 CSV headers remain readable. New provenance and complete quote batches live inside the daily v2 JSON. The batch is saved before the CSV is materialized. A restart can finish a saved batch. GitHub Actions may coalesce pending runs in a concurrency group. Local file locks apply to processes sharing the same ledger directory. Run one scheduler for a given ledger.

State is written before alerts to suppress duplicate signals on retries. A crash between persistence and Discord delivery can suppress an alert. Discord's webhook and the Git-based ledger do not share a transaction. Existing operational state remains in the repository for runner recovery. No credentials, historical results, or generated runtime records are added in this change.

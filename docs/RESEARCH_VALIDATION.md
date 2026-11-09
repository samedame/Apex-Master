# Research validation

Reproduce from the repository root.

```sh
PYTHONPATH=apex_master_bot python research/master_v3/validate.py > /tmp/apex-v3-validation.json
cd apex_master_bot
python -m apex_master_bot v2-replay --data ../research/master_v2/data --published ../research/master_v2/results/master_v2_trades.csv
```

Frozen v2 matched 734 trade dates and tickers with a maximum per-trade net-return difference of 4.45e-12 bp. Its mean was +18.19 bp after 2 bp assumed cost and win rate 56.9%. These are ETF benchmarks. The original selection remains previous VIX close at least 20 and IBS below 0.10 in SPY, QQQ, IWM priority order, one long trade from open to close with no stop.

## Historical ETF comparison

Fixed research family, independent of runtime alerts. Use 1996–2015 development, 2016–2020 validation, and 2021–2026 archive test through November 4. Only previous-session features can affect opening rules. The fixed thresholds are VIX up 1 point, SPY above its 20-day average, at least two of the three ETFs up on the prior day, and prior SPY 20-session annualized realized volatility at least 20%. Compare lowest eligible IBS and a short on the same signal as additional hypotheses. The participation count is a three-ETF proxy. The volatility threshold uses realized history, without fitting a forecast. Rules use neither current-day returns nor final-period parameter selection.

| ETF rule | Test trades | Net bp/trade at 2 bp cost | Holm-adjusted paired comparison |
| --- | ---: | ---: | ---: |
| Frozen v2 | 108 | +18.69 | Reference |
| VIX up ≥ 1 | 70 | −4.16 | 0.132 |
| SPY above 20-day average | 23 | +27.69 | Inconclusive |
| ETF participation ≥ 2 | 5 | +66.95 | Inconclusive |
| Realized volatility ≥ 20% | 39 | +33.45 | 1.000 |
| Lowest eligible IBS | 108 | +26.41 | 0.584 |
| Short on the same signal | 108 | −22.69 | 0.330 |

Baseline mean intervals were +3.71 to +32.41 bp in development, −4.07 to +49.77 bp in validation and −1.71 to +41.69 bp in the historical test. At 5 and 10 bp, historical test means were +15.69 and +10.69 bp and full-notional compounded drawdowns were 6.47% and 7.08%. Lowest IBS raised the historical test mean but worsened drawdown from 6.10% to 7.13% at 2 bp, with a paired daily advantage interval spanning zero. No variant passed the corrected comparison.

The report includes trade-frequency, exposure, compounded equity summary, profit factor, median, downside tail, risk-adjusted session statistics, win intervals, losing streak and VIX strata. A seeded 1,500-replicate circular 20-session bootstrap includes zero-exposure days and estimates uncertainty and drawdown sensitivity. Comparisons resample paired daily returns and correct the fixed six-rule family using Holm. Low counts are inconclusive. Cash idle earns zero. Model costs are a sensitivity, and full-notional results do not represent the $1,500 account.

The opening-gap analysis enters no earlier than 10:30 ET. At 5 bp the delay benchmark had 26 trades at +6.78 bp, negative-gap continuation shorts had 9 at −10.50 bp, negative-gap reversal longs had 9 at +0.50 bp, and the ≥50 bp negative-gap reversal had 5 at +37.91 bp. The gap family is descriptive and inconclusive. Archived hourly opens are prices, not timestamped executable quotes.

## Remaining evidence gaps

The archive test was held separate inside this script. Its dates overlap the previously studied v2 sample, so prospective out-of-sample performance remains unverified. ETF universe selection and survivorship, vendor revisions, publication lag, multiple rounds of historical hypothesis generation, crisis clustering and an incomplete point-in-time session calendar constrain inference. The fixed comparison has no parameter fit or expanding-window retraining. Existing preregistered walk-forward and threshold sweeps remain under `research/master_v2`.

Event exclusion, stop/target path sequencing, alternative close times, a calibrated directional model and options expected returns remain **INCONCLUSIVE**. The forward event calendar contains a selected snapshot of scheduled releases. Its availability timestamps use the verification time rather than an inferred historical announcement date. No historical macro outcomes were filled in. DIA, sector breadth, Treasury yields, oil, dollar, credit, VIX term structure and VWAP were excluded from the new tests because aligned point-in-time coverage or an independent test design was unavailable. Existing v2 asset and historical-era tests remain separate evidence. [BLS schedule](https://www.bls.gov/schedule/2026/) · [Federal Reserve schedule](https://www.federalreserve.gov/newsevents/2026-december.htm)

## Prospective QQQ-first shadow test

The paired test compares the unchanged v2 priority SPY → QQQ → IWM with QQQ → IWM → SPY. Both use the same stored pre-open VIX and IBS inputs and the same thresholds. Only the priority changes. The selection must be recorded before 09:30 ET. A missing or late pre-open check is logged as a skip. After the close, both ETFs are scored open to close with the frozen 2 bp assumption once both daily bars exist. The paired difference is an ETF benchmark with no fills. Days where both arms select the same ticker have a zero difference and only one chain observation per window.

The shadow writes one atomic record per Eastern session under `ledger/shadow/`. It includes the original v2 decision timestamp, shadow selection timestamp, source revision, both choices, quote observations, skip reasons and paired ETF result. Old v2 states and ledgers are outside the shadow write path.

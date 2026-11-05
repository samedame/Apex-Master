# Pre-registration addendum 3 (2026-11-04): are the remaining recommended additions worth adding to Master v2?

Written BEFORE any of these tests were run. Context: Master v2 = prior VIX close >= 20 and prior-day IBS < 0.10, first of SPY/QQQ/IWM, long open to close, net of 2 bp round trip. Its weakest point is that the VIX >= 20 split was found post hoc on the same history. About 130 tests already run; this addendum adds 4 more families and says up front which results change the bot.

## A1  Out-of-sample in time (S&P 500 index, 1970-01-02 to 1992-12-31, before SPY and the usual VIX sample)
- Data: ^GSPC daily OHLC (valid highs/lows from 1970). The index "Open" is unreliable before about 2005 (it often equals the prior close), so v2's open-to-close cannot be tested. Test the SIGNAL instead: buy at the signal day's close, sell at the next close (close to close), net 2 bp.
- Regime proxy (no VIX before 1990): RV21 = annualised standard deviation of the 21 daily log close-to-close returns ending the signal day. Threshold q is the RV21 quantile whose upper-tail share equals the share of days with VIX >= 20 over 1990-2026 (calibrated on 1990-2026, never on 1970-92). Report the proxy-vs-VIX agreement on 1990-2026.
- A1a (primary): mean net return after days with IBS < 0.10 and RV21 >= q, 1970-1992. One-sided H1: mean > 0. Date-block bootstrap, ratio estimator.
- A1b (contrast, reported): same signal with RV21 < q. A1c (reference, reported): the same close-to-close variant on SPY 1993-2026 with VIX >= 20.

## A2  Out-of-sample in assets (20 other equity ETFs, each from its own start date, 1995 to 2026-11-04)
- ETFs: DIA, MDY, XLF, XLK, XLE, XLV, XLP, XLU, XLI, XLB, XLY, EWJ, EWG, EWU, EWZ, EEM, EFA, EWC, EWA, EWH. SPY, QQQ, IWM excluded. Ticker-days (no first-of-order pick), open to close, net 2 bp, previous VIX close (US) as the regime.
- A2a (primary): mean net of ticker-days with own prior-day IBS < 0.10 and VIX >= 20. One-sided H1: mean > 0. Date-block bootstrap on the union of dates, so same-day cross-sectional dependence is respected.
- Reported: A2b within VIX >= 20, IBS < 0.10 minus IBS >= 0.10 (with CI); A2c IBS < 0.10 with VIX < 20; A2d split by group (US sector/size ETFs vs international ETFs) and by half (to 2012 / after).

## A3  Weaker second tier (S&P ETFs, 1993-2026)
- Tier-2 day: VIX >= 20, no ETF among SPY/QQQ/IWM has IBS < 0.10, and the first in the order SPY, QQQ, IWM with 0.10 <= IBS < 0.20 is taken, long open to close, net 2 bp.
- A3a (primary): mean net > 0 one-sided, date-block bootstrap. Reported: n and trades per year, halves (to 2012 / after), CI.
- Combined view (reported): tier 1 at weight 1.0 plus tier 2 at weight 0.5; trades per year, mean bp per unit of tier-1-equivalent risk, annualised information ratio (mean/sd of per-trade weighted return x sqrt(trades per year)), max drawdown; compared with tier 1 alone.
- ADMISSION RULE for adding tier 2 to the bot: Holm-adjusted A3a p < 0.10 AND mean >= +8 bp AND both halves positive AND the combined annualised IR is at least tier 1's. Otherwise it is NOT added.

## A4  Volatility-aware sizing (the 734 tier-1 trades)
- Weights normalised to mean 1: constant; w_up proportional to VIX (bigger in stress); w_dn proportional to 1/VIX (volatility scaling). Report per-trade mean/sd (information ratio), annualised IR, max drawdown, and a year-block bootstrap CI of the difference in per-trade IR versus constant.
- ADMISSION RULE: a weighting replaces constant sizing only if the CI of its IR difference excludes 0 AND both halves (to 2012 / after) show the same sign. Otherwise sizing stays constant.

## A5  Not tested
First-hour entry/exit timing needs long intraday history; free sources give 60 days (5-minute) or 730 days (hourly), the latter already used (n=26 pick days). Not testable now.

## Multiple testing and interpretation
- Holm family: A1a, A2a, A3a (one-sided p). Decision level 0.10, as in earlier addenda.
- A1/A2 change no trading rule. They update the evidence label: SUPPORTED out of sample if A1a or A2a has Holm p < 0.10 with a positive mean; WEAKENED if both means are <= 0; INCONCLUSIVE otherwise.
- Nothing is tuned after seeing results. Any further idea becomes a new addendum.

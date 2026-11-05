# Addendum 2 (written after Addendum 1 results; before any addendum-2 test was run)

## What was seen
IBS<0.10 dip-buy (open->close, lowest-IBS pick) is +7.4 bp net overall (CI +0.05..+14.8) but splits sharply by prior-close VIX:
<15 -5.6 bp, 15-20 -5.2 bp, 20-25 +9.9 bp, >=25 +28.7 bp. This split was NOT registered; it is post-hoc and must be tested as such.
A5 says choosing the lowest-IBS ETF has no value (diff -0.2 bp), so the pick rule for this addendum is a liquidity order: first triggered of SPY, QQQ, IWM.
A7: 0 of 108 scan tests survive Holm. A8: no RVOL-normalcy relation (|rho|<=0.05).

## Tests (Holm over B1,B2)
- B1  Pick frame (first triggered in SPY,QQQ,IWM order; prior IBS<0.10; open->close long; net of 2 bp), restricted to prior-close VIX >= 20.
      Claim: net mean > 0, same sign in both L1 halves (<=2012-12-31, >=2013-01-01).
- B2  Heterogeneity: mean(VIX>=20) - mean(VIX<20) > 0. Threshold-search correction: the statistic is the max over thresholds {15,18,20,22,25}
      of (above - below), with null built from 5,000 circular shifts of the VIX series against the trade series (preserves autocorrelation); min 50 trades each side.
- B3  Vol-normalised return (open->close / (VIX_prior/100/sqrt(252))) by VIX band — descriptive.
- B4  L2 replication (2023-12..2026-11, pick frame, VIX>=20 vs <20) — descriptive sign check (n will be small).
- B5  Walk-forward threshold selection: for each year Y from 2000, choose thr in {0,15,18,20,22,25} maximising net mean on years < Y (min 40 trades), apply in year Y.
      Compare with always-trade and fixed thr=20.
- B6  Cost scenarios 2/5/10/20 bp on VIX>=20 picks; breakeven cost.
- B7  Dependence on crisis years: by-year sums; recompute excluding the two best years and excluding 2008, 2020 and 2022 together; year-block bootstrap CI.
- B8  Trade count in the Master's 5-minute window (2026-08-12..11-04) under this rule.
- B9  Today's state: latest VIX close and prior-day IBS for SPY/QQQ/IWM; what the rule says for the next session.

## Admission
B1 and B2 must both have Holm-adjusted p < 0.10 and B1 same sign in both halves for the VIX>=20 regime condition to be admitted.
If admitted it is described as REGIME-CONDITIONAL; B5 (walk-forward) is reported as the honest estimate of the threshold selection procedure.

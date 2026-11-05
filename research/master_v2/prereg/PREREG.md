# Apex Chronos MASTER v2 — pre-registration (2026-11-04, written before any L1/L2 test was run)

## Purpose
Design a one-trade-per-day intraday strategy on the Apex Chronos foundation (opening-range trap logic on SPY/QQQ/IWM),
using only components that survive independent evidence. Compare it with the existing Apex Master on identical data.

## What is already known (not re-tested to select anything)
- Existing Master hindsight pick: 57 trades, +0.306R (1.2R profile) / +0.601R (2.5R). Live-implementable first_fire
  (tie-break |RVOL-1|): -0.020R / +0.165R. Reproduced from results/exit_variants.csv before this registration.
- The Master's window (60 sessions, 2026-08-12..11-04) is the ONLY 5-minute history available (Yahoo cap), and it is
  the window its thresholds and ranking rule were selected on. It cannot be used as out-of-sample evidence for anything
  the Master selected on it.

## Evidence levels
- L1  daily bars: SPY 1993-, QQQ 1999-, IWM 2000-, to 2026-11-04 (open->close and close->close).
- L2  hourly bars: SPY/QQQ/IWM 2023-12-07..2026-11-04, ~725 sessions each. Bars start 09:30,10:30,...,15:30 (last bar is 30 min).
      Only full 7-bar sessions are used. Independent of the Master's 60-session window except for its last 60 sessions.
- L3  5-minute bars, 12 tickers, 60 sessions (Master's window). Used for (a) engine parity, (b) causal evaluation of the
      final rule, (c) nested leave-block-out validation. Never used alone to admit a component.

## L2/L1 hypothesis family (10 tests, Holm-adjusted together)
Costs: 1.0 bp per side (2 bp round trip) on the underlying; gross also reported. Underlying returns, not option P&L.
Inference: session-block bootstrap (10,000 draws) on date-level means pooled across the three ETFs; one-sided tests in the
direction stated; Holm across all 10.
Splits: Half A = sessions <= 2025-06-30, Half B = >= 2025-07-01.

Definitions (hourly session bars 0..6; OR = bar 0 high/low; prevclose = prior session's last bar close):
- H1 TRAP FADE. For bar k in 1..4: short if High_k > OR_high and Close_k < OR_high and Close_k < Open_k;
  long if Low_k < OR_low and Close_k > OR_low and Close_k > Open_k. First event per ticker-session (skip if both sides in one bar).
  Enter next bar open, exit that bar's close. Statistic: mean of direction*(Close_{k+1}/Open_{k+1}-1) minus the mean
  unconditional return of the same bar slot (drift). Claim: > 0.
- H2 BREAKOUT FOLLOW. For bar k in 1..4: long if Close_k > OR_high and Close_k > Open_k; short if Close_k < OR_low and Close_k < Open_k.
  Same entry/exit/baseline. Claim: > 0.
- H3 RVOL NORMALCY inside H1 events. RVOL_k = Volume_k / mean(Volume of the same slot, prior 20 sessions). Normal band
  0.75 <= RVOL <= 1.33. Statistic: mean directional return (normal) minus (outside). Claim: > 0. Permutation p.
- H4a LATE-DAY MOMENTUM. s = sign(Open_6/prevclose - 1); return = s*(Close_6/Open_6 - 1). Claim: mean > 0.
- H4b same with s = sign(Open_6/Open_0 - 1). Claim: mean > 0.
- H4c H4a restricted to prior-close VIX >= 20. Claim: mean > 0.
- H5a/H5b IBS (L2). Prior-day IBS = (C-L)/(H-L) from daily bars. Long if < 0.10 / short if > 0.90; return = Close_6/Open_0 - 1
  (direction-signed) minus unconditional open->close mean. Claim: > 0.
- H5c/H5d IBS on L1 daily history (SPY 1993-, QQQ, IWM): same definitions, open->close. Claim: > 0.
(Count: H1,H2,H3,H4a,H4b,H4c,H5a,H5b,H5c,H5d = 10.)

## Admission rule for a component in the Master v2
A return-bearing component is admitted only if: pooled net effect > 0, Holm-adjusted p < 0.10, and same sign in both halves.
Otherwise it is either excluded or kept purely as a risk rule with no return claim (and labelled so).

## L3 protocol (intraday strategy evaluation)
- Engine is event-driven and causal: at each 5-minute bar only data up to and including that bar is used; entry is the next bar open.
- One trade per day: the FIRST candidate that passes pre-set absolute gates. No whole-day ranking.
- Primary metrics: mean R per trade (R = 0.9*ATR14 at signal, 0.15R cost, stop on bar close), win rate, PF, max drawdown,
  session-block bootstrap CI, comparison to random-pick distribution and to the Master's live rule.
- Selection among a finite config family (<= 60 configs, counted) is evaluated by leave-one-block-out nested CV (6 blocks of ~10 sessions):
  the reported out-of-sample number is the CV number, not the best in-sample config.
- Final config is frozen only after CV; stress tests (cost x2/x3, 1-bar delay, data-revision, per-block) are reported, not tuned on.

## Honest-limits clause
Any L3 result is on one 60-session, low-VIX regime. It can refute (e.g. a causal rule that loses) but cannot confirm.
The deliverable includes a forward-test registration with kill criteria, same as the existing Master's section 9.

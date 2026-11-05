# Addendum 1 to PREREG.md (written after the 10 registered tests were seen; before any addendum test was run)

## What was seen
Registered result: only H5c (IBS<0.10 long, open->close, L1 daily) is admitted (net +10.1 bp, Holm 0.068, both halves positive).
H1, H2, H3 fail. H4a/b/c fail in the claimed direction and are significantly NEGATIVE (late-day REVERSAL in 2023-26, net ~0 after 2 bp).
Descriptive only (not tested): H2 earns +8.7 bp gross on VIX>=20 days vs ~+1 bp otherwise (n=309 events) — this matches the
project's earlier independent noise-band verdict (high-VIX tercile carries the momentum edge), but the split was looked at here
before being registered, so it is POST-HOC for this addendum.

## Addendum tests (Holm applied within this addendum, separately from the first 10)
- A5  Selection among triggered ETFs (L1). On days where >=2 of SPY/QQQ/IWM have prior IBS<0.10, compare the lowest-IBS pick with the mean of the
      other triggered ETFs (open->close, per-day paired difference). Claim: > 0. Session-block bootstrap.
- A6  (POST-HOC, flagged) H2 restricted to prior-close VIX >= 20 (L2). Claim: net > 0 with same sign in both halves. Admitted as a conditional module only if
      adjusted p < 0.10 AND both halves positive AND the earlier independent noise-band verdict agrees on direction (it does, in-sample for that verdict).
- A7  Exhaustive intraday feature scan (L2, 3 ETFs pooled by date, two-sided, 108 group tests = 6 signal bars x 18 feature groups).
      Features at close of bar k (k=0..5): bar-return sign (2); day-return-from-prevclose sign (2); intraday-IBS tercile <0.15 / mid / >0.85 (3);
      RVOL tercile <0.75 / 0.75-1.33 / >1.33 (3); gap sign with |gap|>0.15% up / down / flat (3); VIX prior <15 / 15-20 / >=20 (3);
      prior-day IBS <0.10 / >0.90 (2). Target: C_k -> C_6 return minus the unconditional mean for that slot. Holm over 108.
      Anything surviving must also have the same sign in both halves and |effect| > 2 bp (cost) to count.
- A8  Cross-instrument RVOL-normalcy check (L3, 9 non-index tickers, P1C and P2 candidates, exit_variants.csv, simple_tp1.2_mb20 and simple_tp2.5_mb20):
      Spearman correlation between candidate R and |RVOL-1|. Claim: negative. Same-window, so it tests the mechanism across instruments, not across time.

## Descriptive robustness for the admitted IBS component (no p-values used for decisions)
D1 threshold sweep 0.05/0.10/0.15/0.20/0.25; D2 VIX bands; D3 trend (SPY vs 200d); D4 gap sign; D5 by decade; D6 by ticker;
D7 max adverse / favourable excursion from open (daily H/L); D8 trade frequency per year (lowest-IBS pick, one ETF per day);
D9 L2 timing profile (return by hourly slot on IBS<0.10 days).

## Rules unchanged
Admission rule from PREREG.md. Costs 2 bp round trip. Halves: L2 split 2025-06-30; L1 split 2012-12-31.

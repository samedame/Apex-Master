"""Charts for Master v2. Usage: python -I s07_charts.py DATA_DIR OUT_DIR"""
import sys
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from common import *

DATA, OUT = sys.argv[1], sys.argv[2]
D = Data(DATA)
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, ORANGE = "#2a78d6", "#eb6834"      # categorical slots 1,2 (validated adjacent pair)

def style(ax):
    ax.set_facecolor(SURF)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)

pk = pd.read_csv(f"{OUT}/ibs_pick_order_l1.csv", parse_dates=["date"]).sort_values("date")
pk["bp"] = (pk.oc - COST) * 1e4
hi = pk[pk.vix >= 20].copy(); lo = pk[pk.vix < 20].copy()

# ---------- Figure 1: cumulative + yearly ----------
fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 8.2), facecolor=SURF, gridspec_kw=dict(height_ratios=[1.35, 1], hspace=0.42))
style(a1)
a1.plot(hi.date, hi.bp.cumsum(), color=BLUE, lw=2)
a1.plot(lo.date, lo.bp.cumsum(), color=ORANGE, lw=2)
a1.axhline(0, color=INK2, lw=0.8)
a1.set_ylabel("Cumulative net return, bp of underlying", color=INK2, fontsize=9)
a1.text(hi.date.iloc[-1], hi.bp.cumsum().iloc[-1], f"  VIX ≥ 20: {len(hi)} trades, {hi.bp.cumsum().iloc[-1]:,.0f} bp", color=INK, va="center", fontsize=9)
a1.text(lo.date.iloc[-1], lo.bp.cumsum().iloc[-1], f"  VIX < 20: {len(lo)} trades, {lo.bp.cumsum().iloc[-1]:,.0f} bp", color=INK, va="center", fontsize=9)
a1.set_xlim(pd.Timestamp("1993-01-01"), pd.Timestamp("2033-06-01"))
a1.set_xticks([pd.Timestamp(f"{y}-01-01") for y in range(1995, 2030, 5)])
a1.set_xticklabels([str(y) for y in range(1995, 2030, 5)])
a1.legend(handles=[plt.Line2D([0], [0], color=BLUE, lw=2, label="Prior-close VIX ≥ 20  (the Master v2 rule)"),
                   plt.Line2D([0], [0], color=ORANGE, lw=2, label="Prior-close VIX < 20  (same IBS signal, calm market)")],
          loc="upper left", frameon=False, fontsize=9, labelcolor=INK)
a1.set_title("Buying an oversold index ETF at the open pays only when volatility is elevated", loc="left", fontsize=12, color=INK, fontweight="bold", pad=22)
a1.text(0, 1.03, "Prior-day IBS < 0.10, first of SPY/QQQ/IWM, long open→close, net of 2 bp round trip, 1993–2026", transform=a1.transAxes, color=INK2, fontsize=9)

style(a2)
by = hi.groupby(hi.date.dt.year).bp.sum()
yrs = np.arange(by.index.min(), by.index.max() + 1); vals = by.reindex(yrs).fillna(0)
a2.bar(yrs, vals.values, color=BLUE, width=0.7)
for y, v in zip(yrs, vals.values):
    if v < 0: a2.bar(y, v, color=BLUE, width=0.7, hatch="////", edgecolor=SURF, linewidth=0)
a2.axhline(0, color=INK2, lw=0.8)
a2.set_ylabel("Net bp per calendar year", color=INK2, fontsize=9)
a2.set_title(f"VIX ≥ 20 trades by year: {int((by>0).sum())} of {len(by)} years with trades were positive", loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
a2.text(2001, vals.loc[2001] - 220, "2001: −2,743 bp\n(grinding bear)", ha="center", va="top", fontsize=8.5, color=INK2)
a2.set_ylim(vals.min() - 900, vals.max() + 300)
fig.text(0.01, 0.005, "Hatched bars are losing years. Years with no qualifying trade are blank. Source: Yahoo Finance daily bars, Cboe VIX; underlying returns, not option P&L.", color=INK2, fontsize=8)
fig.savefig(f"{OUT}/fig1_v2_equity.png", dpi=170, facecolor=SURF, bbox_inches="tight")
plt.close(fig)

# ---------- Figure 2: IBS gradient by regime ----------
rows = []
for t in TICK:
    d = D.daily[t].copy(); d["vix"] = D.vix_prior.reindex(d.index, method="ffill")
    d = d[d.index >= "1993-02-01"].dropna(subset=["ibs_prior", "vix", "oc"]); rows.append(d[["ibs_prior", "vix", "oc"]])
P = pd.concat(rows); P["bp"] = (P.oc - COST) * 1e4
bins = [0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0001]; labs = ["<0.1", "0.1–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–0.9", "≥0.9"]
P["b"] = pd.cut(P.ibs_prior, bins=bins, labels=labs, right=False)
mh = P[P.vix >= 20].groupby("b", observed=True).bp.mean(); ml = P[P.vix < 20].groupby("b", observed=True).bp.mean()
fig, ax = plt.subplots(figsize=(10, 4.6), facecolor=SURF); style(ax)
x = np.arange(len(labs)); w = 0.38
ax.bar(x - w / 2 - 0.01, mh.values, width=w - 0.02, color=BLUE, label="Prior-close VIX ≥ 20")
ax.bar(x + w / 2 + 0.01, ml.values, width=w - 0.02, color=ORANGE, label="Prior-close VIX < 20")
for i, (a, b) in enumerate(zip(mh.values, ml.values)):
    ax.text(i - w / 2, a + (0.7 if a >= 0 else -0.7), f"{a:+.0f}", ha="center", va="bottom" if a >= 0 else "top", fontsize=8.5, color=INK)
    ax.text(i + w / 2, b + (0.7 if b >= 0 else -0.7), f"{b:+.0f}", ha="center", va="bottom" if b >= 0 else "top", fontsize=8.5, color=INK)
ax.set_ylim(-25, 31); ax.axhline(0, color=INK2, lw=0.8); ax.set_xticks(x); ax.set_xticklabels(labs)
ax.tick_params(axis="x", pad=6); ax.set_xlabel("Prior-day IBS: (close − low) / (high − low)", color=INK2, fontsize=9); ax.set_ylabel("Mean open→close, net bp", color=INK2, fontsize=9)
ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper right")
ax.set_title("The IBS effect is a graded gradient in stress and absent in calm markets", loc="left", fontsize=12, color=INK, fontweight="bold", pad=22)
ax.text(0, 1.03, "SPY, QQQ, IWM ticker-days pooled, 1993–2026. Every VIX ≥ 20 day averages −0.1 bp, so this is not a high-volatility drift.", transform=ax.transAxes, color=INK2, fontsize=9)
fig.savefig(f"{OUT}/fig2_ibs_gradient.png", dpi=170, facecolor=SURF, bbox_inches="tight")
plt.close(fig)
print("saved")

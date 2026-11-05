import pandas as pd, numpy as np
df=pd.read_csv("/home/user/Apex_Master/results/exit_variants.csv", parse_dates=['date'])
# use ladder variant that matches Apex foundation but with optimized TP for P1C: we'll evaluate simple_tp1.8 and 2.5 as 'Master exit'
def evaluate(d, label):
    if len(d)==0: print(label,"n=0"); return None
    # 1 per day: ranking - earliest minute, then module priority P1C>P2>P1B>P1A>P3, then rvol closeness to 1
    prio={'P1C':0,'P2':1,'P1B':2,'P1A':3,'P3':4}
    d=d.copy(); d['prio']=d.module.map(prio); d['rvol_score']=(d.rvol-1).abs()
    d=d.sort_values(['date','prio','minute','rvol_score'])
    one=d.groupby('date').head(1).copy()
    dates=pd.date_range(df.date.min(), df.date.max(), freq='B')
    def stats(x):
        if len(x)==0: return "n=0"
        wins=(x.R2>0); eq=x.R2.cumsum()
        dd=(eq-eq.cummax()).min()
        pf=x[x.R2>0].R2.sum()/max(0.01,-x[x.R2<0].R2.sum())
        # bootstrap mean CI
        rng=np.random.default_rng(42); means=[rng.choice(x.R2.values, size=len(x), replace=True).mean() for _ in range(2000)]
        lo,hi=np.percentile(means,[2.5,97.5])
        return f"trades={len(x)} days={len(x)}/{len(dates)} win={wins.mean():.1%} meanR={x.R2.mean():+.3f} (95%CI {lo:+.3f} to {hi:+.3f}) PF={pf:.2f} sumR={x.R2.sum():+.1f} maxDD={dd:.1f}R"
    split=sorted(d.date.unique())[len(sorted(d.date.unique()))//2]
    print(f"\n{label}\n  ALL {stats(one)}\n  TR  {stats(one[one.date<split])}\n  TE  {stats(one[one.date>=split])}")
    return one

for variant in ['simple_tp1.8_mb20','simple_tp2.5_mb20','simple_tp1.2_mb20']:
    d=df[df.exit_variant==variant]
    print("\n########",variant)
    evaluate(d, "Baseline all modules 1/day")
    evaluate(d[d.module.isin(['P1C','P2']) & d.ticker.isin(['SPY','QQQ','IWM'])], "MASTER-A: P1C+P2 index only")
    evaluate(d[d.module=='P1C'], "P1C all tickers")
    evaluate(d[(d.module=='P1C') & d.ticker.isin(['SPY','QQQ','IWM'])], "P1C index only")
    evaluate(d[(d.module=='P1C') & (d.rvol<1.65) & (d.rvol>=0.5)], "P1C RVOL 0.5-1.65 all")
    evaluate(d[(d.module.isin(['P1C','P2'])) & (d.ticker.isin(['SPY','QQQ','IWM'])) & (d.vix_prior<25)], "MASTER-A + VIX<25 (Regime not HIGH/STRESS)")
    evaluate(d[(d.module.isin(['P1C','P2'])) & (d.ticker.isin(['SPY','QQQ','IWM'])) & (d.minute<=120)], "MASTER-A + minute<=120")

# Save master-A trades for 2.5 variant
d=df[df.exit_variant=='simple_tp2.5_mb20']
d=d[(d.module.isin(['P1C','P2'])) & (d.ticker.isin(['SPY','QQQ','IWM'])) & (d.vix_prior<25)]
prio={'P1C':0,'P2':1}; d=d.copy(); d['prio']=d.module.map(prio); d['rvol_score']=(d.rvol-1).abs()
one=d.sort_values(['date','prio','minute','rvol_score']).groupby('date').head(1)
one.to_csv("/home/user/Apex_Master/results/masterA_trades.csv",index=False)
print("\nSaved masterA",len(one))

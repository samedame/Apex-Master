import pandas as pd, numpy as np
df=pd.read_csv("/home/user/Apex_Master/results/exit_variants.csv", parse_dates=['date'])
def stats(x,col='R2'):
    if len(x)==0: return "n=0"
    pf=x[x[col]>0][col].sum()/max(0.01,-x[x[col]<0][col].sum()); eq=x.sort_values('date')[col].cumsum(); dd=(eq-eq.cummax()).min()
    return f"n={len(x)} win={(x[col]>0).mean():.1%} mean={x[col].mean():+.3f} PF={pf:.2f} sum={x[col].sum():+.1f} DD={dd:.1f}"
pool=lambda d: d[(d.module.isin(['P1C','P2']))&(d.ticker.isin(['SPY','QQQ','IWM']))].copy()
for variant,g in df.groupby('exit_variant'):
    d=pool(g); d['rvol_dist']=(d.rvol-1).abs(); d['prio']=d.module.map({'P1C':0,'P2':1})
    one=d.sort_values(['date','prio','rvol_dist']).groupby('date').head(1)
    dates=sorted(one.date.unique()); split=dates[len(dates)//2]
    print(f"{variant:28} ALL {stats(one)} | TR {stats(one[one.date<split])} | TE {stats(one[one.date>=split])}")
# SPY exclusion check (flag as post-hoc)
print("\n--- Post-hoc SPY exclusion (DO NOT adopt without forward test) ---")
for variant in ['simple_tp2.5_mb20','simple_tp1.8_mb20']:
    d=pool(df[df.exit_variant==variant]); d['rvol_dist']=(d.rvol-1).abs(); d['prio']=d.module.map({'P1C':0,'P2':1})
    for tickers,label in [(['QQQ','IWM'],'QQQ+IWM only'),(['SPY','QQQ','IWM'],'all index')]:
        one=d[d.ticker.isin(tickers)].sort_values(['date','prio','rvol_dist']).groupby('date').head(1)
        print(variant,label,stats(one))

import pandas as pd, numpy as np
df=pd.read_csv("/home/user/Apex_Master/results/exit_variants.csv", parse_dates=['date'])
def stats(x):
    if len(x)==0: return "n=0"
    pf=x[x.R2>0].R2.sum()/max(0.01,-x[x.R2<0].R2.sum()); eq=x.sort_values('date').R2.cumsum(); dd=(eq-eq.cummax()).min() if len(eq) else 0
    rng=np.random.default_rng(1); ms=[rng.choice(x.R2.values,size=len(x),replace=True).mean() for _ in range(1500)]; lo,hi=np.percentile(ms,[2.5,97.5])
    return f"n={len(x)} win={(x.R2>0).mean():.1%} mean={x.R2.mean():+.3f} CI[{lo:+.2f},{hi:+.2f}] PF={pf:.2f} sum={x.R2.sum():+.1f} DD={dd:.1f}"
def pick(d, sortcols, ascending):
    return d.sort_values(sortcols, ascending=ascending).groupby('date').head(1)
for variant in ['simple_tp2.5_mb20','simple_tp1.8_mb20']:
    d=df[(df.exit_variant==variant)&(df.module.isin(['P1C','P2']))&(df.ticker.isin(['SPY','QQQ','IWM']))].copy()
    dates=sorted(d.date.unique()); split=dates[len(dates)//2]
    print("\n===",variant)
    variants={
      'priority+earliest': (['date','module','minute'],[True,True,True]),
      'earliest': (['date','minute'],[True,True]),
      'latest': (['date','minute'],[True,False]),
      'highest_zabs': (['date','z'],[True,False]), # z signed? use abs later
      'rvol_closest1': (['date','rvol'],[True,True]),
    }
    d['z_abs']=d.z.abs(); d['rvol_dist']=(d.rvol-1).abs(); d['module_prio']=d.module.map({'P1C':0,'P2':1})
    variants['highest_zabs']=(['date','z_abs'],[True,False])
    variants['rvol_closest1']=(['date','rvol_dist'],[True,True])
    variants['prio+rvol']=(['date','module_prio','rvol_dist'],[True,True,True])
    variants['prio+earliest']=(['date','module_prio','minute'],[True,True,True])
    for name,(cols,asc) in variants.items():
        # groupby sort trick: sort whole then head
        one=d.sort_values(cols[1:],ascending=asc[1:]).groupby('date',as_index=False).head(1) if False else d.sort_values(cols,ascending=asc).groupby('date').head(1)
        print(f"{name:20} ALL {stats(one)} | TR {stats(one[one.date<split])} | TE {stats(one[one.date>=split])}")
    # selectivity: P1C only, z_abs thresholds, rvol thresholds on prio+earliest pick then filter
    base=d.sort_values(['date','module_prio','minute']).groupby('date').head(1)
    for name,mask in [('P1C only days',base.module=='P1C'),('z_abs>0.8',(base.z_abs>0.8)),('rvol<1.2',base.rvol<1.2),('minute<=90',base.minute<=90),('gap_abs<1%',base.gap.abs()<0.01)]:
        sub=base[mask]; print(f"filter {name:20} ALL {stats(sub)} | TR {stats(sub[sub.date<split])} | TE {stats(sub[sub.date>=split])}")

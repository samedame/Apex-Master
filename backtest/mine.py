import pandas as pd, numpy as np
df=pd.read_csv("/home/user/Apex_Master/results/exit_variants.csv")
# use best overall variant per row? Instead analyze simple_tp1.8_mb20 and drift
for variant in ['simple_tp1.8_mb20','simple_tp2.5_mb20','drift_close_tp99','simple_tp0.8_mb20']:
    d=df[df.exit_variant==variant].copy()
    d['is_index']=d.ticker.isin(['SPY','QQQ','IWM'])
    dates=sorted(d.date.unique()); split=dates[len(dates)//2]
    print("\n===",variant,"split",split)
    # subgroup scan single filters
    filters={
      'P1C+index': (d.module=='P1C')&(d.is_index),
      'P1C+notaligned': (d.module=='P1C')&(d.aligned==False),
      'P1C+index+notaligned': (d.module=='P1C')&(d.is_index)&(d.aligned==False),
      'P2+drift-ish index': (d.module=='P2')&(d.is_index),
      'P1C any': d.module=='P1C',
      'P2 any': d.module=='P2',
      'P1C+P2 index': d.module.isin(['P1C','P2'])&(d.is_index),
      'P1C rvol<1': (d.module=='P1C')&(d.rvol<1),
      'P1C minute<45': (d.module=='P1C')&(d.minute<45),
      'P1C short': (d.module=='P1C')&(d.direction==-1),
      'P1C long': (d.module=='P1C')&(d.direction==1),
    }
    for name,m in filters.items():
        sub=d[m]; tr=sub[sub.date<split]; te=sub[sub.date>=split]
        if len(sub)<10: continue
        def s(x): return f"n={len(x)} mean={x.R2.mean():+.3f} win={(x.R2>0).mean():.2f}" if len(x) else "n=0"
        print(f"{name:28} ALL {s(sub)} | TR {s(tr)} | TE {s(te)}")

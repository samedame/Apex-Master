import pandas as pd, numpy as np
df=pd.read_csv("/home/user/Apex_Master/results/exit_variants.csv", parse_dates=['date'])
def get_one(variant, extra_cost=0):
    d=df[(df.exit_variant==variant)&(df.module.isin(['P1C','P2']))&(df.ticker.isin(['SPY','QQQ','IWM']))].copy()
    d['R_adj']=d.R2-extra_cost; d['rvol_dist']=(d.rvol-1).abs(); d['prio']=d.module.map({'P1C':0,'P2':1})
    one=d.sort_values(['date','prio','rvol_dist']).groupby('date').head(1)
    return one
def stats(x,col='R_adj'):
    if len(x)==0: return "n=0"
    pf=x[x[col]>0][col].sum()/max(0.01,-x[x[col]<0][col].sum())
    return f"n={len(x)} win={(x[col]>0).mean():.1%} mean={x[col].mean():+.3f} PF={pf:.2f} sum={x[col].sum():+.1f}"
for variant in ['simple_tp2.5_mb20','simple_tp1.8_mb20']:
    print("\n",variant)
    for cost in [0,0.15,0.30,0.50]:
        one=get_one(variant,cost); print(f" extra_cost={cost:.2f}R {stats(one)}")
    one=get_one(variant,0)
    # 3-fold walk forward by date thirds
    dates=sorted(one.date.unique()); k=len(dates)//3
    for i,(a,b) in enumerate([(0,k),(k,2*k),(2*k,len(dates))]):
        fold=one[one.date.isin(dates[a:b])]; print(f" fold{i+1} {dates[a].date()}..{dates[b-1].date()} {stats(fold)}")
    print(" by module", one.groupby('module').apply(lambda x: stats(x), include_groups=False).to_dict())
    print(" by ticker", one.groupby('ticker').apply(lambda x: stats(x), include_groups=False).to_dict())
    print(" by direction", one.groupby('direction').apply(lambda x: stats(x), include_groups=False).to_dict())
    # permutation: shuffle R within pool? Sign test
    from scipy import stats as st
    print(f" t-test meanR vs 0: t={st.ttest_1samp(one.R_adj,0).statistic:.2f} p={st.ttest_1samp(one.R_adj,0).pvalue:.3f}")
    one.to_csv(f"/home/user/Apex_Master/results/master_final_{variant}.csv",index=False)

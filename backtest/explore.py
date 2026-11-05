import pandas as pd, numpy as np
df=pd.read_csv("/home/user/Apex_Master/results/candidates_v1.csv", parse_dates=['date'])
df['is_index']=df.ticker.isin(['SPY','QQQ','IWM'])
df['gap_abs']=df.gap.abs()
df['z_abs']=df.z.abs()
df['vix_regime']=pd.cut(df.vix_prior,[0,15,20,25,30,100],labels=['CALM','NORMAL','ELEVATED','HIGH','STRESS'])
dates=sorted(df.date.unique()); split=dates[len(dates)//2]
print("split",split, "n dates",len(dates))
def stats(sub):
    if len(sub)==0: return "n=0"
    return f"n={len(sub)} win={(sub.R>0).mean():.2f} meanR={sub.R.mean():+.3f} sumR={sub.R.sum():+.1f} PF={sub[sub.R>0].R.sum()/max(0.01,-sub[sub.R<0].R.sum()):.2f}"
print("\nALL",stats(df))
for name, mask in [
 ("aligned",df.aligned==True),("not aligned",df.aligned==False),
 ("index only",df.is_index),("single names",~df.is_index),
 ("SPY above200",df.spy_above200==True),("SPY below200",df.spy_above200==False),
 ("VIX<20",df.vix_prior<20),("VIX 20-25",df.vix_prior.between(20,25)),("VIX>=25",df.vix_prior>=25),
 ("long",df.direction==1),("short",df.direction==-1),
 ("gap>1%",df.gap_abs>0.01),("gap 0.25-1%",df.gap_abs.between(0.0025,0.01)),
 ("rvol>1.25",df.rvol>1.25),("rvol<1",df.rvol<1),("rvol 1-1.65",df.rvol.between(1,1.65)),
 ("minute<60",df.minute<60),("minute>=60",df.minute>=60),
 ("ibs_prior<0.2",df.ibs_prior<0.2),("ibs_prior>0.8",df.ibs_prior>0.8),
]:
    print(f"{name:22} {stats(df[mask])}")
print("\nBy module x aligned")
print(df.groupby(['module','aligned'])['R'].agg(['count','mean',lambda x:(x>0).mean()]))
print("\nBy module x index")
print(df.groupby(['module','is_index'])['R'].agg(['count','mean',lambda x:(x>0).mean()]))
print("\nBy module x VIX regime")
print(df.groupby(['module','vix_regime'], observed=True)['R'].agg(['count','mean',lambda x:(x>0).mean()]))
print("\nBy ticker")
print(df.groupby('ticker')['R'].agg(['count','mean',lambda x:(x>0).mean(),'sum']).sort_values('mean',ascending=False))
print("\nTrain/Test by module")
for m,g in df.groupby('module'):
    tr=g[g.date<split]; te=g[g.date>=split]
    print(m, "TR",stats(tr),"| TE",stats(te))
print("\nTrain/Test aligned+index")
for m,g in df.groupby('module'):
    for label, gg in [('idx-align',g[(g.is_index)&(g.aligned)]),('name-align',g[(~g.is_index)&(g.aligned)])]:
        tr=gg[gg.date<split]; te=gg[gg.date>=split]
        if len(gg)>=15: print(m,label,"TR",stats(tr),"| TE",stats(te))
# exit variants are embedded; check raw directional drift: time exits only
print("\nCorrelation features vs R")
for c in ['gap_abs','z','rvol','minute','vix_prior','ibs_prior','ema_slope']:
    print(c, df[c].corr(df.R))
df.to_csv("/home/user/Apex_Master/results/candidates_enriched.csv",index=False)

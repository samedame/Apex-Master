import pandas as pd, numpy as np, json, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
df=pd.read_csv("/home/user/Apex_Master/results/exit_variants.csv", parse_dates=['date'])
def build(variant):
    d=df[(df.exit_variant==variant)&(df.module.isin(['P1C','P2']))&(df.ticker.isin(['SPY','QQQ','IWM']))].copy()
    d['rvol_dist']=(d.rvol-1).abs(); d['prio']=d.module.map({'P1C':0,'P2':1})
    one=d.sort_values(['date','prio','rvol_dist']).groupby('date').head(1).sort_values('date')
    one['cumR']=one.R2.cumsum(); one['cumR_after2x_cost']=(one.R2-0.15).cumsum()
    return one
master=build('simple_tp1.2_mb20'); runner=build('simple_tp2.5_mb20')
master.to_csv("/home/user/Apex_Master/results/MASTER_trades_tp1.2.csv",index=False)
runner.to_csv("/home/user/Apex_Master/results/RUNNER_trades_tp2.5.csv",index=False)
def stats(x):
    r=x.R2; pf=r[r>0].sum()/max(0.01,-r[r<0].sum()); eq=r.cumsum(); dd=(eq-eq.cummax()).min()
    return dict(n=int(len(x)), win=float((r>0).mean()), meanR=float(r.mean()), PF=float(pf), sumR=float(r.sum()), maxDD_R=float(dd))
summary={"master_tp1.2":stats(master),"runner_tp2.5":stats(runner),
 "master_by_ticker":{k:stats(v) for k,v in master.groupby('ticker')},
 "master_by_module":{k:stats(v) for k,v in master.groupby('module')}}
json.dump(summary, open("/home/user/Apex_Master/results/summary.json","w"), indent=2)
print(json.dumps(summary,indent=2))
# charts
plt.figure(figsize=(10,4.5))
plt.plot(master.date, master.cumR, label='Master TP 1.2R (70% win profile)', lw=2)
plt.plot(master.date, master.cumR_after2x_cost, label='Master + extra 0.15R/trade cost', lw=1.5, ls='--')
plt.plot(runner.date, runner.R2.cumsum(), label='Runner TP 2.5R (higher PF, lower win)', lw=1.5, alpha=0.8)
plt.axhline(0,color='k',lw=0.8); plt.ylabel('Cumulative R'); plt.title('Apex Chronos MASTER — cumulative R (1 trade/day, 57 trades, Aug–Nov 2026 5m sample)'); plt.legend(fontsize=8); plt.tight_layout(); plt.savefig("/home/user/Apex_Master/results/equity_curve.png",dpi=180); plt.close()
# module raw chart
cand=pd.read_csv("/home/user/Apex_Master/results/candidates_enriched.csv")
m=cand.groupby('module').R.mean()
plt.figure(figsize=(8,3.8)); colors=['#c0392b' if v<0 else '#27ae60' for v in m.values]
plt.bar(m.index,m.values,color=colors); plt.axhline(0,color='k',lw=0.8); plt.ylabel('Mean R / candidate (original Apex exits)'); plt.title('Raw Apex modules on 5m data: all negative before Master filtering'); plt.tight_layout(); plt.savefig("/home/user/Apex_Master/results/raw_modules.png",dpi=180); plt.close()
print(master[['date','ticker','module','direction','minute','rvol','R2','exit2']].head(10).to_string(index=False))

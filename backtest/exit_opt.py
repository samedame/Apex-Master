import pandas as pd, numpy as np, sys
sys.path.insert(0,'/home/user/Apex_Master/backtest')
from engine import load, TICKERS
cand=pd.read_csv("/home/user/Apex_Master/results/candidates_enriched.csv")
# cache day frames + ATR stop_dist replication
cache={}
def get_day(ticker, date):
    key=(ticker,str(date))
    if key in cache: return cache[key]
    df=load(ticker); g=df[df.index.date.astype(str)==str(date)].copy()
    if len(g)==0: cache[key]=None; return None
    tr=pd.concat([g['High']-g['Low'], (g['High']-g['Close'].shift()).abs(), (g['Low']-g['Close'].shift()).abs()],axis=1).max(axis=1)
    g['atr']=tr.rolling(14,min_periods=5).mean()
    cache[key]=g; return g

def sim(g, idx, direction, stop_dist, tp_R, max_bars, stop_mode='close'):
    if idx+1>=len(g): return None
    entry=g['Open'].iloc[idx+1]; peak=0; tp_hit=False; rem=1; real=0
    for j in range(idx+1, min(len(g), idx+1+max_bars)):
        h,l,c=g['High'].iloc[j],g['Low'].iloc[j],g['Close'].iloc[j]
        if direction==1: highR=(h-entry)/stop_dist; lowR=(l-entry)/stop_dist; closeR=(c-entry)/stop_dist
        else: highR=(entry-l)/stop_dist; lowR=(entry-h)/stop_dist; closeR=(entry-c)/stop_dist
        peak=max(peak,highR)
        if stop_mode=='intrabar' and not tp_hit and lowR<=-1:
            return real-1.0-0.15,"stop",j-idx
        if not tp_hit and highR>=tp_R:
            real+=0.5*tp_R; rem=0.5; tp_hit=True
        if tp_hit:
            floor=max(0.6*tp_R,0.72*peak)
            if lowR<=floor: return real+rem*floor-0.15,"trail",j-idx
        elif closeR<=-1:
            return real+rem*closeR-0.15,"stop",j-idx
    last=g['Close'].iloc[min(len(g)-1,idx+max_bars)]
    final=(last-entry)/stop_dist if direction==1 else (entry-last)/stop_dist
    return real+rem*final-0.15,"time",max_bars

def sim_simple(g, idx, direction, stop_dist, tp_R, max_bars):
    # single target / stop, no partial
    if idx+1>=len(g): return None
    entry=g['Open'].iloc[idx+1]
    for j in range(idx+1, min(len(g), idx+1+max_bars)):
        h,l,c=g['High'].iloc[j],g['Low'].iloc[j],g['Close'].iloc[j]
        if direction==1: highR=(h-entry)/stop_dist; lowR=(l-entry)/stop_dist; closeR=(c-entry)/stop_dist
        else: highR=(entry-l)/stop_dist; lowR=(entry-h)/stop_dist; closeR=(entry-c)/stop_dist
        if highR>=tp_R: return tp_R-0.15,"tp",j-idx
        if closeR<=-1: return closeR-0.15,"stop",j-idx
    last=g['Close'].iloc[min(len(g)-1,idx+max_bars)]
    final=(last-entry)/stop_dist if direction==1 else (entry-last)/stop_dist
    return final-0.15,"time",max_bars

rows=[]
# locate bar index by timestamp
cand['ts']=pd.to_datetime(cand['ts'])
for _,r in cand.iterrows():
    g=get_day(r.ticker, r.date)
    if g is None: continue
    # find position
    try: idx=g.index.get_loc(r.ts)
    except: 
        # ts string may include tz; try search
        matches=np.where(g.index==r.ts)[0]
        if len(matches)==0: continue
        idx=matches[0]
    if isinstance(idx, slice): continue
    atr=g['atr'].iloc[idx]
    if pd.isna(atr): continue
    stop_dist=max(atr*0.9, r.close*0.0008)
    for tp in [0.8,1.2,1.8,2.5]:
        for mb in [8,13,20]:
            s=sim_simple(g,idx,r.direction,stop_dist,tp,mb)
            if s: rows.append({**r.to_dict(),'exit_variant':f'simple_tp{tp}_mb{mb}','R2':s[0],'exit2':s[1]})
    for tp in [1.2,1.8]:
        s=sim(g,idx,r.direction,stop_dist,tp,13,stop_mode='intrabar')
        if s: rows.append({**r.to_dict(),'exit_variant':f'ladder_intra_tp{tp}','R2':s[0],'exit2':s[1]})
    # hold to close no stop (drift)
    s=sim_simple(g,idx,r.direction,stop_dist,99,78)
    if s: rows.append({**r.to_dict(),'exit_variant':'drift_close_tp99','R2':s[0],'exit2':s[1]})
out=pd.DataFrame(rows)
out.to_csv("/home/user/Apex_Master/results/exit_variants.csv",index=False)
print(out.groupby('exit_variant')['R2'].agg(['count','mean',lambda x:(x>0).mean(),'sum']).sort_values('mean',ascending=False).to_string())
print("\nBy module x best variants")
for v,g in out.groupby('exit_variant'):
    print("\n",v)
    print(g.groupby('module')['R2'].agg(['count','mean',lambda x:(x>0).mean()]).round(3).to_string())

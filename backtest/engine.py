"""Apex Chronos -> Apex Chronos Master research engine (5m adaptation).
Entry modules adapted faithfully in logic; timeframe compressed 1m->5m (Yahoo limit).
Outcome: underlying R-multiple with Apex-style ladder simplified:
 stop=-1R, TP1 at module TP/stop ratio scaled, half at TP1 + trailing floor, time exit.
Costs: 0.04% round-trip underlying equivalent (slippage/spread proxy) deducted as R cost.
"""
import pandas as pd, numpy as np, os, glob
DATA="/home/user/Apex_Master/data"
TICKERS=["SPY","QQQ","IWM","NVDA","TSLA","META","AMD","AAPL","MSFT","AMZN","COIN","MSTR"]

def load(t, interval="5m"):
    d=pd.read_csv(f"{DATA}/{t}_{interval}.csv", index_col=0, parse_dates=True)
    d.index=pd.to_datetime(d.index, utc=True).tz_convert("America/New_York")
    d=d.between_time("09:30","15:55") if interval=="5m" else d
    return d

def daily_context():
    spy=pd.read_csv(f"{DATA}/SPY_1d.csv", index_col=0, parse_dates=True)
    vix=pd.read_csv(f"{DATA}/VIX_1d.csv", index_col=0, parse_dates=True)
    if isinstance(spy.index, pd.DatetimeIndex): pass
    spy.index=pd.to_datetime(spy.index).tz_localize(None).normalize()
    vix.index=pd.to_datetime(vix.index).tz_localize(None).normalize()
    ctx=pd.DataFrame(index=spy.index)
    ctx['spy_close']=spy['Close']; ctx['sma50']=spy['Close'].rolling(50).mean(); ctx['sma200']=spy['Close'].rolling(200).mean(); ctx['sma20']=spy['Close'].rolling(20).mean()
    ctx['vix_prior']=vix['Close'].shift(1).reindex(ctx.index, method='ffill')
    ctx['spy_above50']=(ctx.spy_close>ctx.sma50).shift(1)
    ctx['spy_above200']=(ctx.spy_close>ctx.sma200).shift(1)
    # IBS prior day, RSI2 proxy
    ctx['ibs_prior']=((spy['Close']-spy['Low'])/(spy['High']-spy['Low'])).shift(1)
    delta=spy['Close'].diff(); gain=delta.clip(lower=0).rolling(2).mean(); loss=(-delta.clip(upper=0)).rolling(2).mean()
    ctx['rsi2_prior']=(100-100/(1+gain/loss)).shift(1)
    # fear proxy percentile of VIX (expanding, 252 min)
    v=vix['Close'].reindex(ctx.index, method='ffill')
    ctx['vix_pct']=v.rolling(750, min_periods=100).apply(lambda x: (x[:-1]<x[-1]).mean(), raw=True)
    ctx=ctx.shift(0)  # spy_above etc already shifted; vix_prior shifted
    return ctx

CTX=daily_context()

def simulate(df, idx, direction, stop_dist, tp_R, max_bars):
    """idx=index position of signal bar; enter next bar open. Returns R, exit_reason, bars"""
    if idx+1>=len(df): return None
    entry=df['Open'].iloc[idx+1]
    if stop_dist<=0 or np.isnan(stop_dist): return None
    peak_R=0; tp1_hit=False; remaining=1.0; realized=0.0
    for j in range(idx+1, min(len(df), idx+1+max_bars)):
        o,h,l,c=df['Open'].iloc[j],df['High'].iloc[j],df['Low'].iloc[j],df['Close'].iloc[j]
        # R based on close for stop (per Apex: stop on close, not low) - check intrabar TP/floor
        if direction==1:
            highR=(h-entry)/stop_dist; lowR=(l-entry)/stop_dist; closeR=(c-entry)/stop_dist
        else:
            highR=(entry-l)/stop_dist; lowR=(entry-h)/stop_dist; closeR=(entry-c)/stop_dist
        peak_R=max(peak_R, highR)
        if not tp1_hit and highR>=tp_R:
            realized+=0.5*tp_R; remaining=0.5; tp1_hit=True
        if tp1_hit:
            floor=max(0.6*tp_R, 0.72*peak_R) if peak_R>tp_R else 0.6*tp_R
            if lowR<=floor:
                realized+=remaining*floor; return realized-0.15, "trail", j-idx  # cost in R approx 0.15
        elif closeR<=-1.0:
            realized+=remaining*closeR; return realized-0.15, "stop", j-idx
    # time exit at close of last bar
    last=df['Close'].iloc[min(len(df)-1, idx+max_bars)]
    finalR=(last-entry)/stop_dist if direction==1 else (entry-last)/stop_dist
    realized+=remaining*finalR
    return realized-0.15, "time", max_bars

def candidates_for(ticker):
    df=load(ticker)
    spy=load("SPY")
    spy_day={}
    # SPY intraday alignment maps
    spy['vwap_spy']=(spy['Close']*spy['Volume']).groupby(spy.index.date).cumsum()/spy['Volume'].groupby(spy.index.date).cumsum()
    spy_map={ts:(row['Close']>row['vwap_spy']) for ts,row in spy.iterrows()}
    # precompute cumulative-volume RVOL map: (date_str, slot) -> cumvol / prior20 mean cumvol
    _volmat={}
    for _d,_gg in df.groupby(df.index.date):
        _volmat[str(_d)]=np.cumsum(_gg['Volume'].values)
    _sorted_dates=sorted(_volmat.keys())
    RVOL_MAP={}
    for _di,_d in enumerate(_sorted_dates):
        _prior=_sorted_dates[max(0,_di-20):_di]
        if not _prior: continue
        for _i,_v in enumerate(_volmat[_d]):
            _vals=[_volmat[_pd][_i] for _pd in _prior if len(_volmat[_pd])>_i]
            if _vals: RVOL_MAP[(_d,_i)]=_v/np.mean(_vals)
    out=[]
    df['date']=df.index.date
    for date, g in df.groupby('date'):
        g=g.copy(); idxs=list(g.index)
        if len(g)<60: continue
        # daily prev close from intraday previous day
        # use index position in full df
        first_pos=df.index.get_loc(idxs[0])
        if first_pos==0: continue
        prev_close=df['Close'].iloc[first_pos-1]
        open_px=g['Open'].iloc[0]; gap=(open_px/prev_close-1)
        # indicators cumulative
        g['cumvol']=g['Volume'].cumsum()
        g['vwap']=(g['Close']*g['Volume']).cumsum()/g['cumvol']
        g['ema9']=g['Close'].ewm(span=9, adjust=False).mean(); g['ema21']=g['Close'].ewm(span=21, adjust=False).mean()
        # RVOL approx: volume so far vs 20d avg total volume scaled - use rolling from full history per bar timestamp later simplified: volume of bar vs median same slot
        # SD from open intraday realized
        g['ret_from_open']=g['Close']/open_px-1
        intraday_sd=g['Close'].pct_change().std()
        # ORs
        or5_high=g['High'].iloc[0]; or5_low=g['Low'].iloc[0]
        or15=g.iloc[:3]; or15_high=or15['High'].max(); or15_low=or15['Low'].min()
        range75_high=g.iloc[:15]['High'].max(); range75_low=g.iloc[:15]['Low'].min()
        # ATR proxy stop: 14-bar ATR at signal
        tr=pd.concat([g['High']-g['Low'], (g['High']-g['Close'].shift()).abs(), (g['Low']-g['Close'].shift()).abs()],axis=1).max(axis=1)
        atr=tr.rolling(14, min_periods=5).mean()
        # RVOL cumulative vs trailing 20 sessions at same slot (from df history)
        dctx=CTX.loc[pd.Timestamp(date)] if pd.Timestamp(date) in CTX.index else None
        fired=set()
        for i in range(3, len(g)-2):
            ts=idxs[i]; m=i*5  # minutes since open approx
            row=g.iloc[i]; pos=df.index.get_loc(ts)
            if np.isnan(atr.iloc[i]): continue
            stop_dist=max(atr.iloc[i]*0.9, row['Close']*0.0008)
            vol_slot=g['Volume'].iloc[max(0,i-2):i+1].mean()
            rvol_proxy=float(RVOL_MAP.get((str(date), i), 1.0))
            z=float((row['Close']-row['vwap'])/(atr.iloc[i]+1e-9))
            spy_bull=spy_map.get(ts, np.nan)
            base=dict(ticker=ticker,date=str(date),ts=str(ts),minute=m, gap=gap, rvol=rvol_proxy, z=z,
                      spy_bull=bool(spy_bull) if not pd.isna(spy_bull) else None,
                      vix_prior=float(dctx['vix_prior']) if dctx is not None and not pd.isna(dctx['vix_prior']) else np.nan,
                      spy_above200=bool(dctx['spy_above200']) if dctx is not None and not pd.isna(dctx['spy_above200']) else None,
                      spy_above50=bool(dctx['spy_above50']) if dctx is not None and not pd.isna(dctx['spy_above50']) else None,
                      ibs_prior=float(dctx['ibs_prior']) if dctx is not None and not pd.isna(dctx['ibs_prior']) else np.nan,
                      vix_pct=float(dctx['vix_pct']) if dctx is not None and not pd.isna(dctx['vix_pct']) else np.nan,
                      close=float(row['Close']), vwap=float(row['vwap']),
                      ema_slope=float(row['ema9']/g['ema9'].iloc[max(0,i-3)]-1) if i>=3 else 0.0)
            def add(module, direction, tp_R, max_bars):
                if module in fired: return
                sim=simulate(g, i, direction, stop_dist, tp_R, max_bars)
                if sim is None: return
                R, reason, bars=sim
                fired.add(module)
                out.append({**base,'module':module,'direction':direction,'R':R,'exit':reason,'bars':bars,
                            'aligned': (direction==1 and spy_bull) or (direction==-1 and not spy_bull),
                            'quality': abs(gap)*100 + abs(z)})
            # P1A Gap-Trap fade
            if 5<=m<=59 and abs(gap)>0.0025:
                direction=-1 if gap>0 else 1
                through = (row['Close']<or5_low and row['Close']<row['vwap']) if gap>0 else (row['Close']>or5_high and row['Close']>row['vwap'])
                ema_side = (row['Close']<row['ema9']) if gap>0 else (row['Close']>row['ema9'])
                side_prev = (row['Close']>prev_close) if gap>0 else (row['Close']<prev_close)  # still on gap side of prev close (per summary)
                if through and ema_side and side_prev: add('P1A', direction, 90/26, 10)
            # P1B Confirmed Gap+ORB15 (long + mirrored short tested as P1B)
            if 18<=m<=64 and i>=5:
                if gap>=0.0035 and (g['Close'].iloc[i-2:i+1]>or15_high).all() and row['ema9']>=row['ema21']:
                    add('P1B', 1, 50/25, 12)
                if gap<=-0.0035 and (g['Close'].iloc[i-2:i+1]<or15_low).all() and row['ema9']<=row['ema21']:
                    add('P1B', -1, 50/25, 12)
            # P1C ORB trap reject (short bull-trap + long bear-trap)
            if 16<=m<=104:
                prev=g.iloc[i-1]
                if prev['High']>or15_high and row['Close']<or15_high and row['Close']<row['ema9'] and row['Close']<row['Open'] and row['Close']>=row['vwap']*0.998:
                    add('P1C', -1, 45/28, 13)
                if prev['Low']<or15_low and row['Close']>or15_low and row['Close']>row['ema9'] and row['Close']>row['Open']:
                    add('P1C', 1, 45/28, 13)
            # P2 Midday range-wall pin fade
            if 75<=m<=239:
                if row['High']>=range75_high and row['Close']<row['Open'] and row['Close']<range75_high:
                    add('P2', -1, 16/20, 16)
                if row['Low']<=range75_low and row['Close']>row['Open'] and row['Close']>range75_low:
                    add('P2', 1, 16/20, 16)
            # P3 Afternoon squeeze reclaim
            if 210<=m<=319:
                # flush condition retained in v2 features below (see reclaim logic)
                if row['Close']<row['vwap']*0.996 and g.iloc[i-1]['Close']<row['vwap'] and row['Close']>row['ema9'] and row['Close']>g.iloc[i-1]['Close']:
                    add('P3', 1, 65/28, 10)
                if row['Close']>row['vwap']*1.004 and g.iloc[i-1]['Close']>row['vwap'] and row['Close']<row['ema9'] and row['Close']<g.iloc[i-1]['Close']:
                    add('P3', -1, 65/28, 10)
    return out

if __name__=="__main__":
    allc=[]
    for t in TICKERS:
        c=candidates_for(t); print(t, len(c)); allc+=c
    df=pd.DataFrame(allc)
    df.to_csv("/home/user/Apex_Master/results/candidates_v1.csv", index=False)
    print(df.shape)
    if len(df):
        print(df.groupby('module')['R'].agg(['count','mean',lambda x:(x>0).mean(),'sum']).rename(columns={'<lambda_0>':'win'}))
        print(df.groupby(['module','exit']).size())

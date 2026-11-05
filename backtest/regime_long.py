import pandas as pd, numpy as np
spy=pd.read_csv("/home/user/Apex_Master/data/GSPC_1d_long.csv", index_col=0, parse_dates=True)
vix=pd.read_csv("/home/user/Apex_Master/data/VIX_1d_long.csv", index_col=0, parse_dates=True)
for d in [spy,vix]:
    if isinstance(d.columns, pd.MultiIndex): pass
df=pd.DataFrame(index=spy.index)
df['close']=spy['Close']; df['high']=spy['High']; df['low']=spy['Low']; df['open']=spy['Open']
df['vix']=vix['Close'].reindex(df.index, method='ffill')
df=df.dropna(subset=['close'])
df['sma50']=df.close.rolling(50).mean(); df['sma200']=df.close.rolling(200).mean()
df['ibs']=(df.close-df.low)/(df.high-df.low)
delta=df.close.diff(); gain=delta.clip(lower=0); loss=-delta.clip(upper=0)
rs=gain.rolling(2).mean()/loss.rolling(2).mean(); df['rsi2']=100-100/(1+rs)
df['fwd1']=df.close.shift(-1)/df.close-1; df['fwd5']=df.close.shift(-5)/df.close-1; df['fwd21']=df.close.shift(-21)/df.close-1
df['min5']=(df.low.shift(-5).rolling(5, min_periods=1).min() if False else np.nan)
# forward drawdown 5d: min low in next 5 / close -1
lows=df.low.values; closes=df.close.values
fwd_dd5=np.full(len(df), np.nan)
for i in range(len(df)-5): fwd_dd5[i]=lows[i+1:i+6].min()/closes[i]-1
df['fwd_dd5']=fwd_dd5
df=df[df.index>="1991-01-01"]
def s(x, col='fwd1'):
    x=x.dropna(subset=[col]); return f"n={len(x)} P(up)={(x[col]>0).mean():.1%} avg={x[col].mean()*100:+.3f}%"
print("Base fwd1", s(df)); print("Base fwd5", s(df,'fwd5')); print("Base fwd21", s(df,'fwd21'))
for name,m in [('IBS<0.10',df.ibs<0.10),('IBS>0.90',df.ibs>0.90),('RSI2<10',df.rsi2<10),('RSI2>90',df.rsi2>90),
               ('SPX<200d & falling proxy close<sma200',df.close<df.sma200),('SPX>200d',df.close>df.sma200),
               ('VIX>30',df.vix>30),('VIX<15',df.vix<15),('VIX 20-25',df.vix.between(20,25))]:
    sub=df[m]; print(f"{name:35} fwd1 {s(sub)} | fwd5 {s(sub,'fwd5')} | fwd21 {s(sub,'fwd21')} | P(dd5>2%)={(sub.fwd_dd5<-0.02).mean():.1%}")
# split eras
for era,m in [('1991-2010',df.index<="2010-12-31"),('2011-2026',df.index>"2010-12-31")]:
    print("\n",era)
    for name,mm in [('IBS<0.10',df.ibs<0.10),('VIX>30',df.vix>30),('close<200d',df.close<df.sma200)]:
        sub=df[m&mm]; print(name, "fwd21", s(sub,'fwd21'), "fwd vol proxy std fwd5", f"{sub.fwd5.std()*100:.2f}%")
# VIX vs fwd realized vol (5d)
df['rv5_fwd']=df.close.pct_change().shift(-5).rolling(5).std()  # approx not needed
print("\nFear/magnitude replication: VIX quintile vs |fwd5| and P(dd)")
df['vix_q']=pd.qcut(df.vix,5,duplicates='drop')
print(df.groupby('vix_q',observed=True).agg(n=('fwd5','size'), avg_fwd5=('fwd5',lambda x:x.mean()*100), abs_fwd5=('fwd5',lambda x:x.abs().mean()*100), p_dd2=('fwd_dd5',lambda x:(x<-0.02).mean()*100)).round(2).to_string())
df.to_csv("/home/user/Apex_Master/results/regime_long_daily.csv")

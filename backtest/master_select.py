#!/usr/bin/env python3
"""Live-selection logic for Apex Chronos MASTER: given today's candidate list (dicts with
ticker, module, minute, rvol, direction, prior IBS, fear, VIX/regime), return the ONE trade or NO TRADE.
This is the exact rule set backtested in policy2.py / make_final.py."""
def quality_score(c, regime_final="NORMAL", fear=50, ibs_prior=None):
    s=50.0
    s+=20*(1-min(abs(c['rvol']-1.0),1.0))
    if c['module']=='P1C': s+=10
    if c['minute']<=120: s+=10
    if ibs_prior is not None and ibs_prior<0.10 and c['direction']==1: s+=5
    if 41<=fear<=80: s+=5
    if c['rvol']>1.65: s-=15
    return s

def select_one(candidates, regime_final="NORMAL", fear=50, ibs_prior=None, event_day=False):
    if event_day or regime_final in ("HIGH","STRESS"):
        return {"action":"NO TRADE","reason":f"regime gate: {regime_final} / event={event_day}"}
    pool=[c for c in candidates if c['ticker'] in ("SPY","QQQ","IWM") and c['module'] in ("P1C","P2") and c['rvol']<=1.65]
    if not pool: return {"action":"NO TRADE","reason":"no surviving P1C/P2 index candidate"}
    for c in pool: c['score']=quality_score(c, regime_final, fear, ibs_prior)
    pool.sort(key=lambda c: (-c['score'], abs(c['rvol']-1.0), c['minute']))
    best=pool[0]
    if best['score']<60: return {"action":"NO TRADE","reason":f"best score {best['score']:.0f} < 60","best":best}
    size="HALF" if (regime_final=="ELEVATED" or best['score']<75) else "FULL"
    return {"action":"TRADE","size":size, **best,
            "plan":"stop -1.0R close-based, target +1.2R, time exit 100m, hard flat 15:55 ET"}
if __name__=="__main__":
    demo=[{"ticker":"SPY","module":"P1C","direction":-1,"minute":40,"rvol":1.04},
          {"ticker":"QQQ","module":"P1C","direction":1,"minute":55,"rvol":1.48}]
    print(select_one(demo, regime_final="NORMAL", fear=55, ibs_prior=0.08))

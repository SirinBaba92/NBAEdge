"""Nachbau der alten EloEngine (models/elo.py) fuer den Backtest. Liest nur data/cache.
Prueft gegen das gespeicherte Modell: python analysis/old_engine_replica.py"""
import numpy as np, math
from collections import defaultdict
from datetime import datetime


def d(g):
    return datetime.strptime(g['date'][:10], '%Y-%m-%d').date()

def run(games, K=20.0, mov='cur', carry=0.0, kboost=0.0, n0=15, hca=100.0, post_w=1.0,
        total_alpha=0.1, snapshot=True):
    """Replica der EloEngine.process_game mit optionalen Varianten.
    mov: 'cur' = K*2.2*ln(m+1); '538' = K*((m+3)^0.8)/(7.5+0.006*dr)
    carry: Anteil, um den Ratings beim Saisonwechsel zu 1500 zurueckgezogen werden
    kboost: zusaetzlicher K-Multiplikator in den ersten n0 Saisonspielen (linear abfallend)
    """
    R={}; off=defaultdict(float); de=defaultdict(float); last={}; form=defaultdict(list)
    cur_season={}; gp=defaultdict(int)  # Spiele pro Team in aktueller Saison (nur Regular Season)
    rows=[]; season_end={}
    prev_season=None
    for g in games:
        s=g['season']
        if prev_season is not None and s!=prev_season:
            season_end[prev_season]=dict(R)
            if carry>0:
                for t in R: R[t]=1500+(1-carry)*(R[t]-1500)
            gp=defaultdict(int)
        prev_season=s
        h=g['home_team']['full_name']; a=g['visitor_team']['full_name']
        hp=int(g['home_team_score']); ap=int(g['visitor_team_score']); gd=d(g)
        def rest(t):
            if t not in last: return 0.0
            dd=(gd-last[t]).days
            if dd==1: return -1.5
            if dd>=3: return 0.45
            return 0.0
        def frm(t):
            hist=form[t][-10:]
            if not hist: return 0.5
            w=np.arange(1,len(hist)+1,dtype=float); return float(np.dot(hist,w)/w.sum())
        hr,ar=rest(h),rest(a); hf,af=frm(h),frm(a)
        he=R.get(h,1500.)+hca+hr+(hf-.5)*40
        ae=R.get(a,1500.)+ar+(af-.5)*40
        diff=he-ae
        exp=1/(1+10**(-(diff)/400))
        hw=1 if hp>ap else 0
        # Total-Prognose (vor Update)
        exp_total=((off[h]+de[a])/2+(off[a]+de[h])/2)
        post=g.get('postseason',False)
        rows.append((s,int(post),gp[h],gp[a],diff,hf-af,hr-ar,hp-ap,hw,exp_total,hp+ap,
                     R.get(h,1500.),R.get(a,1500.),exp))
        m=abs(hp-ap)
        if mov=='cur':
            k=K*2.2*math.log(m+1)
        else:
            wd=diff if hw else -diff
            k=K*((m+3)**0.8)/(7.5+0.006*wd)
        if kboost>0 and not post:
            for_t=min(gp[h],gp[a])
            k*=1+kboost*max(0.0,(n0-for_t)/n0)
        if post: k*=post_w
        R[h]=R.get(h,1500.)+k*(hw-exp)
        R[a]=R.get(a,1500.)+k*((1-hw)-(1-exp))
        al=total_alpha
        off[h]=(1-al)*off[h]+al*hp; de[h]=(1-al)*de[h]+al*ap
        off[a]=(1-al)*off[a]+al*ap; de[a]=(1-al)*de[a]+al*hp
        form[h].append(hw); form[a].append(1-hw)
        last[h]=gd; last[a]=gd
        if not post:
            gp[h]+=1; gp[a]+=1
    season_end[prev_season]=dict(R)
    cols=['season','post','gp_h','gp_a','diff','fdiff','rdiff','margin','hw','exp_total','total','rh','ra','p_elo']
    arr=np.array(rows,dtype=float)
    return {c:arr[:,i] for i,c in enumerate(cols)}, season_end


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bt_common import load_games
    from models.elo import EloEngine
    games = load_games()
    res, se = run(games)
    eng = EloEngine.load()
    last = se[max(se)]
    diff = max(abs(last[t] - eng.ratings[t]) for t in eng.ratings)
    print("max. Abweichung Ratings Nachbau vs. gespeichertes Modell: %.6f" % diff)

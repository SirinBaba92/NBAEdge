"""Messung zu app.py:423 (engine.predict mit us_today() statt Spieltag). Nur Lesezugriffe, kein Netz, nichts gespeichert.
Aufruf: venv/bin/python analysis/messung_app423.py"""
import json, pickle, statistics as st, sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.projection import compute_projection  # noqa: E402

NY = ZoneInfo("America/New_York")
snap = json.load(open(ROOT / "data/tracking/projection_snapshots.json"))["games"]
out = []
P = out.append

# a) Häufigkeit
tot = bad = 0; games_bad = set(); ex = []; diffs = Counter()
for k, g in snap.items():
    gd = date.fromisoformat(g["game_date"])
    for v in g["versions"]:
        us = datetime.fromisoformat(v["saved_at"]).astimezone(NY).date()
        tot += 1
        d = (gd - us).days
        if d: bad += 1; games_bad.add(k); diffs[d] += 1; ex.append((k.split("|")[0], v["saved_at"], us.isoformat(), d, g["home"], g["away"]))
P(f"a) Versionen gesamt {tot}, an anderem US-Tag als Spieltag gespeichert: {bad} ({100*bad/tot:.1f} %); betroffene Spiele {len(games_bad)} von {len(snap)}")
P(f"   Abstand Spieltag minus Speicher-US-Tag (Tage): {dict(sorted(diffs.items()))}  (+1 = Spiel am Folgetag, Prognose mit 'heute' = Spieltag-1)")
for e in ex[:6]: P("   Bsp: Spieltag %s, gespeichert %s (US %s), Diff %+d, %s - %s" % (e[0], e[1], e[2], e[3], e[4], e[5]))
P("   Hinweis: US-Tag = saved_at nach New York; Prognose und Speicherung liegen ggf. Minuten auseinander (Näherung).")

def load(p): return pickle.load(open(p, "rb"))
def stats(xs):
    return f"Mittel {st.mean(xs):.3f}, Streuung {st.pstdev(xs):.3f}, Max {max(xs):.3f}, n={len(xs)}"

def run(label, model_for):
    P(f"\nb) {label}")
    res = {-1: [], 1: []}; ch = {-1: 0, 1: 0}; base_ch = 0
    for k, g in snap.items():
        gd = date.fromisoformat(g["game_date"]); m = model_for(gd)
        mk = g["versions"][-1]["projection"]
        def proj(d):
            p = m.predict(g["home"], g["away"], d)
            return compute_projection(p, market_total=mk.get("market_total"), market_spread=mk.get("market_spread"), game_date=g["game_date"])
        b = proj(gd)
        for s in (-1, 1):
            q = proj(gd + timedelta(days=s))
            res[s].append((abs(q["exp_spread"] - b["exp_spread"]), abs(q["exp_total"] - b["exp_total"]), abs(q["home_win_prob"] - b["home_win_prob"]) * 100))
            if abs(q["exp_spread"] - b["exp_spread"]) > 0.5: ch[s] += 1
    for s in (-1, 1):
        r = res[s]
        P(f"   Datum Spieltag{s:+d}: |Δ exp_spread| {stats([x[0] for x in r])}")
        P(f"                     |Δ exp_total|  {stats([x[1] for x in r])}")
        P(f"                     |Δ Siegchance| (Prozentpunkte) {stats([x[2] for x in r])}")
        P(f"     Spiele mit |Δ exp_spread| > 0,5: {ch[s]} von {len(r)}")

cur = load(ROOT / "data/elo_model.pkl")
P(f"Heutiges Modell: Stand {cur.ratings_as_of()}")
run("Variante 1 (Auftrag): heutiges Modell für alle Spiele. ACHTUNG: last_game liegt bei vielen Teams NACH dem Spieltag -> Ruhetage dort 0, Effekt unterschätzt.", lambda gd: cur)
cache = {}
def hist(gd):
    p = ROOT / f"data/model_history/elo_model_{(gd - timedelta(days=1)).isoformat()}.pkl"
    if p not in cache: cache[p] = load(p)
    return cache[p]
run("Variante 2 (realistischer): Modellstand vom Vortag des Spieltags (data/model_history), also mit richtigem last_game/Form", hist)

# c) welche Eingabe wirkt
P("\nc) Im Elo-predict() wirkt das Datum nur über _rest_factor (models/elo.py:69): days=1 -> -1,5 Elo (B2B), 2 -> 0, >=3 -> +0,45, <=0 -> 0; rest_days-Anzeige. Form, Ratings, Total, Saison hängen nicht am Datum (Saison/Playoff: is_playoff_date(game_date) nutzt bereits den Spieltag).")
print("\n".join(out))
(ROOT / "analysis/results/app423_messung_teil2.txt").write_text("\n".join(out) + "\n")

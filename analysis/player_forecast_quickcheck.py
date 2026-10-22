"""Grobe Pruefung der Spieler-Punkte-Prognose (engine/player_forecast.py) an 2025-26: 500 zufaellige Spieler-Spiele, nur Vorwissen (Spiele vor dem Spieltag),
Spread 0 (historische Spreads liegen nicht vor). Je Spieler-Spiel alle Meilensteine N mit Prognose zwischen 3 % und 97 %; 5 Stufen der Prognose gegen die Trefferquote.
Nur lesend (Cache data/cache/player_games_2025-26.json). Aufruf: venv/bin/python analysis/player_forecast_quickcheck.py [Anzahl] [Startwert]"""
import collections, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from data import player_history as ph
from engine import player_forecast as pf

n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 500
rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 42)
rows = [r for r in ph.season_rows("2025-26", with_recorder=False)]
by = collections.defaultdict(list)
for r in rows:
    by[r["person_id"]].append(r)
for v in by.values():
    v.sort(key=lambda r: (r["date"], r["game_id"]), reverse=True)
pool = []
for pid, v in by.items():
    for i, r in enumerate(v):
        prior = v[i + 1:]
        if len(prior) >= 10 and sum(x["minutes"] for x in prior) / len(prior) >= 12:
            pool.append((pid, r, prior))
sample = rng.sample(pool, n_samples)
bins = collections.defaultdict(lambda: [0, 0.0, 0])          # Stufe -> [Anzahl, Summe Prognose, Treffer]
mins_err, pts_err = [], []
for pid, r, prior in sample:
    fc = pf.forecast_player(pid, r["date"], games=prior)
    if not fc["ok"]:
        continue
    mins_err.append(fc["minutes"]["mean"] - r["minutes"]); pts_err.append(fc["expected_points"] - r["points"])
    for n, p in fc["p_ge"].items():
        if 0.03 <= p <= 0.97:
            b = min(4, int(p * 5))
            bins[b][0] += 1; bins[b][1] += p; bins[b][2] += r["points"] >= n
print(f"{len(mins_err)} Spieler-Spiele aus 2025-26 (Vorwissen = nur frühere Spiele, Spread 0). UNGEPRÜFT.")
print(f"Minuten: mittlerer Fehler {sum(mins_err)/len(mins_err):+.2f}, mittlerer Betragsfehler {sum(abs(e) for e in mins_err)/len(mins_err):.2f}")
print(f"Punkte:  mittlerer Fehler {sum(pts_err)/len(pts_err):+.2f}, mittlerer Betragsfehler {sum(abs(e) for e in pts_err)/len(pts_err):.2f}")
print("Stufe der Prognose | Anzahl | mittlere Prognose | Trefferquote | Abweichung")
total, dev = 0, 0.0
for b in sorted(bins):
    c, s, h = bins[b]
    print(f"{b*20:>3}-{b*20+20:<3}%            | {c:>6} | {100*s/c:>16.1f}% | {100*h/c:>11.1f}% | {100*(h/c - s/c):+.1f}")
    total += c; dev += c * abs(h / c - s / c)
print(f"mittlere absolute Abweichung (nach Anzahl gewichtet): {100*dev/total:.1f} Prozentpunkte")

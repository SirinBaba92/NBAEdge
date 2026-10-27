"""
Messungen zur Pruefung des Wegs der Siegchance (ELO -> Siegchance -> Anzeige / Value Bets). NUR LESEND: liest data/cache, data/tracking, data/pregame_lines.json, das Pickle (nur laden);
schreibt nichts (Ausgabe auf der Konsole; der Bericht analysis/reports/winner_path_audit.txt wurde von Hand aus diesen Zahlen erstellt).
Aufruf (aus dem Projektordner):  venv/bin/python analysis/audit_winner_path.py
"""
import json
import sys
import warnings
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.stats import norm

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from bt_common import load_games  # noqa: E402
import replica_tunable as rt  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

kw = lambda n: (n or "").split()[-1].lower()

# ---- 1) vertauschte Heim/Gast-Zuordnung zwischen BallDontLie (App) und Odds API
snaps = json.loads((ROOT / "data/tracking/projection_snapshots.json").read_text())["games"]
pre = json.loads((ROOT / "data/pregame_lines.json").read_text())
n_match = n_rev = 0
rev = []
for key, g in snaps.items():
    ev = [e for e in pre.values() if {kw(e.get("home_team")), kw(e.get("away_team"))} == {kw(g["home"]), kw(g["away"])} and abs(float(e.get("commence") or 0) - datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")).timestamp()) < 6 * 3600]
    if ev:
        n_match += 1
        if kw(ev[0]["home_team"]) != kw(g["home"]):
            n_rev += 1
            rev.append((key, ev[0]["home_team"]))
print(f"[1] Snapshot-Spiele mit Odds-Event: {n_match}; Heim/Gast vertauscht: {n_rev} {rev}")
# Odds-Cache (alle Events, die der Odds-API-Cache kennt) gegen BallDontLie-Spiele aus games_2025/upcoming ist nicht moeglich ohne Historie; Neutralplatz-Spiele 2025-26 (Spielerdatei: beide 'home' = False)
rows = json.loads((ROOT / "data/cache/player_games_2025-26.json").read_text())["rows"]
byg = defaultdict(lambda: defaultdict(set))
for r in rows:
    byg[r["game_id"]][r["team"]].add(r["home"])
neutral = [g for g, t in byg.items() if sum(True in v for v in t.values()) != 1]
print(f"[1] Neutralplatz-/Auslandsspiele 2025-26 (beide Teams 'Gast' im NBA-Log): {len(neutral)} von {len(byg)}")

# ---- 3) Datum: date.today() (Berliner Systemzeit) statt US-Spieltag in engine.predict
games = load_games(2015, 2025)
rows_, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
sel = np.where((rows_["season"] == 2025) & (rows_["post"] == 0))[0]
last, d_changes, bucket = {}, [], Counter()
def rest(days):
    return -1.5 if days == 1 else (0.45 if days >= 3 else 0.0)
for i, g in enumerate(games):
    h, a = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
    d = datetime.strptime(g["date"][:10], "%Y-%m-%d").date()
    if i in set(sel):
        dh = (d - last[h]).days if h in last else None
        da = (d - last[a]).days if a in last else None
        r0 = (rest(dh) if dh is not None else 0.0) - (rest(da) if da is not None else 0.0)
        r1 = (rest(dh + 1) if dh is not None else 0.0) - (rest(da + 1) if da is not None else 0.0)
        d_changes.append(r1 - r0)
        bucket[(dh == 1, da == 1)] += 1
    last[h] = last[a] = d
dc = np.array(d_changes)
print(f"[3] 2025-26: Rest-Differenz-Aenderung bei +1 Tag Datumsfehler: Spiele {len(dc)}, betroffen {int((dc != 0).sum())} ({100 * (dc != 0).mean():.0f} %), mittlere |Aenderung| {np.abs(dc).mean():.2f} ELO = {np.abs(dc).mean() / 50:.3f} Punkte Spread, maximal {np.abs(dc).max():.2f} ELO = {np.abs(dc).max() / 50:.3f} Punkte")
print(f"[3] Back-to-back-Anteile 2025-26 (Heim B2B, Gast B2B): {dict(bucket)}")
# Staerke des Rest-Effekts im Modell gegen die Realitaet: Residuum (Marge - Modell-Spread) nach B2B-Konstellation, 2017-2025
sel_all = np.where((rows_["post"] == 0) & (rows_["season"] >= 2017))[0]
last, res_by = {}, defaultdict(list)
for i, g in enumerate(games):
    h, a = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
    d = datetime.strptime(g["date"][:10], "%Y-%m-%d").date()
    dh = (d - last[h]).days if h in last else 9
    da = (d - last[a]).days if a in last else 9
    if i in set(sel_all):
        resid = rows_["margin"][i] - rows_["diff"][i] / 50.0
        res_by[("Heim B2B, Gast nicht" if dh == 1 and da != 1 else "Gast B2B, Heim nicht" if da == 1 and dh != 1 else "beide B2B" if dh == 1 and da == 1 else "keiner B2B")].append(resid)
    last[h] = last[a] = d
for k, v in res_by.items():
    v = np.array(v)
    print(f"[3/6] 2017-2025 {k:<22} n {len(v):>6}: Ø Residuum (Marge minus Modell-Spread) {v.mean():+.2f} Pkt (+-{1.96 * v.std() / np.sqrt(len(v)):.2f})")
print("[3/6] Modell-Rest-Wirkung: B2B -1,5 ELO = -0,03 Punkte (REST_DAYS_WEIGHT 0,015 * 100)")

# ---- 4) Zeitfenster-Filter in fetch_upcoming_games (naive gegen tz-bewusste Zeit)
u = json.loads((ROOT / "data/upcoming_cache.json").read_text())["games"]
now = datetime.now(timezone.utc)
passed_by_error = 0
for g in u:
    try:
        gt = datetime.fromisoformat(g.get("date", "").replace("Z", "+00:00"))
        _ = gt > now - timedelta(hours=3)
    except Exception as ex:
        passed_by_error += 1
        err = type(ex).__name__
print(f"[4] fetch_upcoming_games: {passed_by_error} von {len(u)} Spielen laufen in den Fehlerzweig des Zeitfensters ({err if passed_by_error else '-'}); das Feld 'date' ist nur ein Datum, z. B. {u[0]['date']!r}")

# ---- 5/6) Siegchance: Normalverteilung (Anzeige) gegen Elo-Logistik (Value Bets)
d_abs, flips, n = [], 0, 0
for key, g in snaps.items():
    v = g["versions"][-1]["projection"]
    if v.get("home_win_prob_elo") is None:
        continue
    n += 1
    d_abs.append(abs(v["home_win_prob"] - v["home_win_prob_elo"]))
    flips += (v["home_win_prob"] > 0.5) != (v["home_win_prob_elo"] > 0.5)
d_abs = np.array(d_abs)
print(f"[5] Anzeige (Normal um Spread) gegen Logistik (Value Bets), {n} Spiele mit beiden Werten: Ø |Differenz| {100 * d_abs.mean():.1f} PP, max {100 * d_abs.max():.1f} PP, unterschiedlicher Favorit in {flips}")
# Rundung der Prozentanzeige
bad = 0
for k in range(0, 10001):
    p = k / 10000
    if round(p * 100) + round((1 - p) * 100) != 100:
        bad += 1
print(f"[6] Prozentanzeige: Summe Heim+Gast != 100 bei {bad} von 10001 Wahrscheinlichkeiten")
sp = np.array([g["versions"][-1]["projection"]["exp_spread"] for g in snaps.values()])
print(f"[6] Wertebereich: Siegchance-Grenzen 3-97 % entsprechen Spreads von {13.2 * norm.ppf(0.03):+.1f} bis {13.2 * norm.ppf(0.97):+.1f}; groesster |Spread| in den Snapshots {np.abs(sp).max():.1f}")
print("[5] Mischung: Markt-Anteil 25 % wirkt nur auf den SPREAD (exp_spread = 0,75 Modell + 0,25 Markt); die Siegchance der Anzeige folgt daraus. Value Bets: 30 % Modell (Logistik) + 70 % Sharp-Quote (engine/ev.py blend_probabilities)")

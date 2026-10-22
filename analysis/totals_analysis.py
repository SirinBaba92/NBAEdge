"""Totals-Analyse (Phase B): Wirkung der Playoffs auf die Off/Def-Werte des alten Modells.
Liest nur data/cache und das gespeicherte alte Modell (nur lesen). Aufruf: venv/bin/python analysis/totals_analysis.py"""
import datetime, sys, warnings
from collections import defaultdict
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import load_games, RESULTS
from bt_v2 import run_v2
from models.elo import EloEngine
from models.points_rating import PointsRatingModel

games = load_games()
eng = EloEngine.load()

# --- (i) Ligamittel Regular Season vs. Playoffs -------------------------------
print("(i) Mittlerer Total je Spiel")
print("Saison | Regular Season | Playoffs | Differenz")
league = {}
for s in range(2015, 2026):
    rs = np.mean([g["home_team_score"] + g["visitor_team_score"] for g in games if g["season"] == s and not g["postseason"]])
    po = np.mean([g["home_team_score"] + g["visitor_team_score"] for g in games if g["season"] == s and g["postseason"]])
    league[s] = (rs, po)
    print(f"{s} | {rs:.1f} | {po:.1f} | {po-rs:+.1f}")

# --- (ii) Off+Def (EMA alpha 0.1, Start 0, wie altes Modell) zum RS-Ende vs. nach den Playoffs ---
t = defaultdict(float)
snap_rs = {}                      # Stand nach dem letzten Regular-Season-Spiel des Teams
last_rs_idx = {}
for i, g in enumerate(games):
    if not g["postseason"]:
        for tm in (g["home_team"]["full_name"], g["visitor_team"]["full_name"]):
            last_rs_idx[(g["season"], tm)] = i
state_end_rs, state_end_po, played_po = {}, {}, defaultdict(set)
cur = None
for i, g in enumerate(games):
    tot = g["home_team_score"] + g["visitor_team_score"]
    for tm in (g["home_team"]["full_name"], g["visitor_team"]["full_name"]):
        t[tm] = 0.9 * t[tm] + 0.1 * tot
        if g["postseason"]:
            played_po[g["season"]].add(tm)
        if last_rs_idx.get((g["season"], tm)) == i:
            state_end_rs[(g["season"], tm)] = t[tm]
    if i + 1 == len(games) or games[i + 1]["season"] != g["season"]:
        for tm in t:
            state_end_po[(g["season"], tm)] = t[tm]
# Konsistenz mit dem gespeicherten Modell
chk = max(abs(state_end_po[(2025, tm)] - (eng.off_ratings[tm] + eng.def_ratings[tm])) for tm in eng.ratings)
print(f"\nPruefung Nachbau Off+Def vs. gespeichertes Modell (max. Abweichung): {chk:.6f}")
print("\n(ii) Mittelwert Off+Def ueber alle 30 Teams (Saisonende), Regular-Season-Ende vs. nach Playoffs")
print("Saison | RS-Ende | nach PO | Diff | davon Playoff-Teams Diff | RS-Mittel der Liga")
rows = []
for s in range(2016, 2026):
    teams = [tm for (ss, tm) in state_end_rs if ss == s]
    rs = np.mean([state_end_rs[(s, tm)] for tm in teams]); po = np.mean([state_end_po[(s, tm)] for tm in teams])
    pt = [tm for tm in teams if tm in played_po[s]]
    dpt = np.mean([state_end_po[(s, tm)] - state_end_rs[(s, tm)] for tm in pt])
    rows.append((s, rs, po, po - rs, dpt))
    print(f"{s} | {rs:.1f} | {po:.1f} | {po-rs:+.1f} | {dpt:+.1f} ({len(pt)} Teams) | {league[s][0]:.1f}")
print("\n2025 (Stand fuer den Saisonstart 2026/27): Mittel Off+Def im Pickle = %.1f; Liga-Mittel Regular Season 2025 = %.1f, Playoffs = %.1f"
      % (np.mean([eng.off_ratings[tm] + eng.def_ratings[tm] for tm in eng.ratings]), league[2025][0], league[2025][1]))

# --- (iii) heute Abend: Rohtotals alt vs. Varianten ---------------------------------
mk = {("New York Knicks", "Philadelphia 76ers"): 232.0, ("San Antonio Spurs", "Oklahoma City Thunder"): 230.7, ("Detroit Pistons", "Boston Celtics"): 219.8}
variants = {
    "alt (Pickle)": None,
    "B EMA ohne Playoffs": dict(tmode="ema", t_alpha=0.10, t_rc=0.0, t_po=False),
    "C EMA ohne PO + Uebernahme 50 %": dict(tmode="ema", t_alpha=0.10, t_rc=0.5, t_po=False),
    "D Liga-Niveau + Abw., ohne PO, Ueb. 50 %": dict(tmode="dev", t_alpha=0.10, t_rc=0.5, t_po=False, L_alpha=0.02),
    "G nested gewaehlt (EMA a=.15, rc .5, mit PO)": dict(tmode="ema", t_alpha=0.15, t_rc=0.5, t_po=True),
}
print("\n(iii) Roh-Totals fuer die drei Spiele von heute (Markt: Knicks-76ers 232.0, Spurs-OKC 230.7, Pistons-Celtics 219.8)")
out = {}
for nm, prm in variants.items():
    vals = []
    for (h, a), m in mk.items():
        if prm is None:
            vals.append(eng.predict(h, a, datetime.date(2026, 10, 20))["expected_total"])
        else:
            mod = run_v2(games, prm)[1]
            vals.append(mod.predict(h, a, datetime.date(2026, 10, 20))["expected_total"])
    out[nm] = vals
    print(f"{nm:46s}", " | ".join(f"{v:.1f} (Markt {m:.1f}, Diff {v-m:+.1f})" for v, m in zip(vals, mk.values())))

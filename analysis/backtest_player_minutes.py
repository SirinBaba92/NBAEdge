"""
Minutenprognose des Spieler-Modells (engine/player_forecast.py): Ist-Stand und Varianten. NUR LESEND: data/cache (player_games_*.json, games_*.json), schreibt nur analysis/reports/player_minutes.txt
(Zwischenstaende liegen in einem Temp-Ordner). Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):
  venv/bin/python analysis/backtest_player_minutes.py                 alles (Replays parallel, danach Auswertung)
  venv/bin/python analysis/backtest_player_minutes.py --analysis-only    nur Auswertung der vorhandenen Zwischenstaende
  venv/bin/python analysis/backtest_player_minutes.py --pilot           Probelauf 2025-26, erste 20 Spieltage (schreibt nichts)

Aufbau wie analysis/backtest_player_markets.py (Adapter analysis/bt_player_adapter.py: Verlauf nur vor Spieltag D, Kader aus den Spielerzeilen, Spread/Total aus dem kausalen Team-Replay ohne Markt).
A = rohe Prognose, B = Teamabgleich (Ausfaelle unbekannt; Variante C entfaellt). Saisons: 2023-24 (ohne Vorsaison im Cache: Verlauf nur aus der laufenden Saison), 2024-25, 2025-26.
2026-27 (nur wenige Tage) hat im Cache keine Teamspiele fuer den Replay und bleibt aussen vor.
Varianten (nur im Replay, Produktivcode unveraendert; Konstanten werden im Prozess ueberschrieben): Starter-Obergrenze 36 (heute) / 38 / 40 / keine; Gewichtung der Spiele: heute (Halbwertszeit 8) /
Saisonschnitt (gleich gewichtet) / letzte 5 / letzte 10 / Mischung 50 % Saisonschnitt + 50 % letzte 5.
Meilenstein-Chancen: P(Punkte >= k), k = 1..60; verglichen werden dieselben (Spieler, k) Zeilen: die der heutigen Variante mit 5 % <= p <= 95 %.
"""
import json
import sys
import time
import warnings
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_player_markets as bpm  # noqa: E402
from bt_player_adapter import Adapter, p_array  # noqa: E402
from engine import player_forecast as pf  # noqa: E402

TMP = Path("/private/tmp/claude-501/-Users-baranalturk-Desktop-NBAEdge/76ad3d4f-3f38-4b80-9c53-3d58597b513a/scratchpad/pm")
OUT = HERE / "reports" / "player_minutes.txt"
bpm.EVAL = {"2023-24": 2023, "2024-25": 2024, "2025-26": 2025}
SEASONS = ["2023-24", "2024-25", "2025-26"]
TASKS = [("2023-24", "base")] + [(s, v) for s in ("2024-25", "2025-26") for v in ("base", "cap38", "cap40", "capnone", "sason", "l5", "l10", "mix")]
EPS = 1e-9


# ---------------------------------------------------------------------------------------------- Varianten (nur im Prozess)
def weights_season(games, season):
    """Wie pf.game_weights, aber ohne Abfall innerhalb der Saison (gleich gewichtet); Anteil der laufenden Saison n / (n + K) bleibt."""
    cur = [i for i, g in enumerate(games) if g["season"] == season]
    prev = [i for i, g in enumerate(games) if g["season"] != season]
    if not games:
        return []
    share_cur = 1.0 if not prev else (0.0 if not cur else len(cur) / (len(cur) + pf.PRIOR_GAMES_K))
    out = [0.0] * len(games)
    for idx, share in ((cur, share_cur), (prev, 1.0 - share_cur)):
        for i in idx:
            out[i] = share / len(idx)
    return out


def weights_last(n):
    def f(games, season):
        k = min(n, len(games))
        w = [(1.0 / k if i < k else EPS) for i in range(len(games))]
        s = sum(w)
        return [x / s for x in w]
    return f


def weights_mix(games, season):
    a, b = weights_season(games, season), weights_last(5)(games, season)
    return [0.5 * x + 0.5 * y for x, y in zip(a, b)]


def install_variant(v):
    if v == "cap38":
        pf.STARTER_MINUTES_CAP = 38.0
    elif v == "cap40":
        pf.STARTER_MINUTES_CAP = 40.0
    elif v == "capnone":
        pf.STARTER_MINUTES_CAP = 1e9
    elif v == "sason":
        pf.game_weights = weights_season
    elif v == "l5":
        pf.game_weights = weights_last(5)
    elif v == "l10":
        pf.game_weights = weights_last(10)
    elif v == "mix":
        pf.game_weights = weights_mix


class AdapterAB(Adapter):
    def team_variants(self, team, is_home, ctx, day, played):          # Variante C (Ausfaelle bekannt) entfaellt: spart die zweite Teamrechnung
        B = pf.team_match(team, is_home, ctx, day, None, None)
        return B, B, set()


# ---------------------------------------------------------------------------------------------- Lauf einer Saison/Variante
def run_task(args):
    season, variant, days_limit = args
    t0 = time.time()
    install_variant(variant)
    all_rows, flat, store, games, replay = bpm.setup()
    adapter = AdapterAB(store)
    sg, ctl = bpm.prepare_games(all_rows[season], season, games, replay)
    if days_limit:
        keep_days = set(sorted({g["date"] for g in sg})[:days_limit])
    else:
        keep_days = None
    # Minuten je (Saison, Team, Spieler) aus den Zeilen: Vorjahr-Kennzeichen und Rang "bis dahin"
    minutes_by = defaultdict(float)
    for r in flat:
        if r["minutes"] > 0:
            minutes_by[(r["season"], r["team"], r["person_id"])] += r["minutes"]
    prev_season = bpm.bpa.prev_season(season)
    has_prev = any(k[0] == prev_season for k in minutes_by)
    prev_cum = defaultdict(dict)
    for (s, t, p), m in minutes_by.items():
        if s == prev_season:
            prev_cum[t][p] = m
    cum = defaultdict(lambda: defaultdict(float))
    team_gp = defaultdict(int)
    pending, cur_day = [], None
    n_games = len(sg)
    cols = defaultdict(list)
    P_A, P_B = [], []

    def flush():
        for g_ in pending:
            for r_ in g_["rows"]:
                if r_["minutes"] > 0:
                    cum[r_["team"]][r_["person_id"]] += r_["minutes"]
        pending.clear()

    for gi, g in enumerate(sg):
        if g["date"] != cur_day:
            flush()
            cur_day = g["date"]
        gp_home, gp_away = team_gp[g["home"]], team_gp[g["away"]]
        team_gp[g["home"]] += 1; team_gp[g["away"]] += 1
        pending.append(g)
        if keep_days is not None and g["date"] not in keep_days:
            continue
        day = g["date"]
        adapter.set_day(day, (g["home"], g["away"]))
        for side, team, is_home, gp in (("home", g["home"], True, gp_home), ("away", g["away"], False, gp_away)):
            played_rows = [r for r in g["rows"] if r["team"] == team and r["minutes"] > 0]
            if not played_rows:
                continue
            out, info = adapter.forecast_team(team, is_home, g["ctx"], day, played_rows)
            base_cum = cum[team] if gp >= 5 or not prev_cum.get(team) else prev_cum[team]
            order = sorted(base_cum.items(), key=lambda kv: (-kv[1], kv[0]))
            rank_cum = {p: i + 1 for i, (p, _) in enumerate(order)}
            tspread = g["ctx"]["exp_spread"] if is_home else -g["ctx"]["exp_spread"]
            for rec in out:
                r = rec["row"]; A, Bv = rec["variants"]["A"], rec["variants"]["B"]
                pid = rec["person_id"]
                cols["gi"].append(gi); cols["date"].append(int(day.replace("-", ""))); cols["home"].append(int(is_home)); cols["gp"].append(gp); cols["half"].append(int(gi >= n_games // 2))
                cols["ot"].append(g["ot"]); cols["absm"].append(abs(g["margin"])); cols["tspread"].append(tspread); cols["min"].append(r["minutes"]); cols["pts"].append(r["points"])
                cols["pid"].append(pid); cols["rank_cum"].append(rank_cum.get(pid, 99))
                cols["new"].append(int(minutes_by.get((prev_season, team, pid), 0.0) <= 0) if has_prev else -1)
                cols["rank_B"].append(rec["rank_B"] or 99); cols["in_rot"].append(int(rec["in_rot_B"]))
                cols["emin_A"].append(A["minutes"]["mean"]); cols["epts_A"].append(A["expected_points"])
                cols["emin_B"].append(Bv["minutes"]["mean"]); cols["epts_B"].append(Bv["expected_points"])
                P_A.append(p_array(A).astype(np.float32)); P_B.append(p_array(Bv).astype(np.float32))
    arr = {k: np.asarray(v) for k, v in cols.items()}
    arr["pA"], arr["pB"] = np.asarray(P_A), np.asarray(P_B)
    arr["n_games_total"] = np.array([n_games])
    if not days_limit:
        np.savez_compressed(TMP / f"{season}_{variant}.npz", **arr)
    return season, variant, len(arr["gi"]), time.time() - t0, adapter.checked_rows, adapter.max_date_seen


def replays(pilot=False):
    if pilot:
        print(run_task(("2025-26", "base", 20)))
        return
    t0 = time.time()
    with Pool(7, maxtasksperchild=1) as pool:           # jede Aufgabe in einem frischen Prozess: die Varianten ueberschreiben Konstanten im Prozess
        for res in pool.imap_unordered(run_task, [(s, v, 0) for s, v in TASKS if not (TMP / f"{s}_{v}.npz").exists()]):
            print(f"fertig {res[0]} {res[1]}: {res[2]} Zeilen, {res[3]:.0f} s (gesamt {time.time() - t0:.0f} s); geprueft {res[4]} Zeilen, juengste {res[5]}", flush=True)


if __name__ == "__main__":
    if "--pilot" in sys.argv:
        replays(True)
    elif "--analysis-only" not in sys.argv:
        replays()
        print("Replays fertig")

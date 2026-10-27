"""
Ausfaelle von Stammspielern: Wirkung auf Minuten und Punkte der Mitspieler und Guete der heutigen Neuberechnung (engine/player_forecast.py: team_match mit absent_ids).
NUR LESEND: data/cache (player_games_*.json, games_*.json), schreibt nur analysis/reports/player_absence.txt (Zwischenstaende im Temp-Ordner). Keine API-Calls, Produktivmodell unveraendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_absence.py   (Replays 2 Saisons parallel, dann Auswertung; mit --analysis-only nur Auswertung)

Aufbau wie analysis/backtest_player_markets.py / backtest_player_minutes.py (Adapter analysis/bt_player_adapter.py: Verlauf nur vor Spieltag D). Je Team und Spiel (ab dem 11. Teamspiel der Saison):
 Ausgefallen = Spieler der Top 8 des Teams nach Minuten in der laufenden Saison bis dahin, der im Spiel 0 Minuten hat oder keine Zeile (Teamwechsel danach zaehlt nicht als Ausfall).
 Das ist Wissen aus der Zukunft (Obergrenze). A = rohe Prognose, B = Teamabgleich ohne Ausfaelle ("ohne Ausfaelle gerechnet"), C = Teamabgleich mit den Ausfaellen als absent_ids (die heutige Neuberechnung).
Bewertet werden nur Spieler mit Prognose UND Minuten > 0 im Spiel. Bootstrap IMMER nach Spielen (beide Teams eines Spiels zusammen).
"""
import sys
import time
import warnings
from collections import defaultdict
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

TMP = Path("/private/tmp/claude-501/-Users-baranalturk-Desktop-NBAEdge/76ad3d4f-3f38-4b80-9c53-3d58597b513a/scratchpad/pa")
TMP.mkdir(parents=True, exist_ok=True)
SEASONS = ["2024-25", "2025-26"]
MIN_TEAM_GAMES = 10
TOP_N = 8


def run_task(args):
    season, days_limit = args
    t0 = time.time()
    all_rows, flat, store, games, replay = bpm.setup()
    adapter = Adapter(store)
    sg, ctl = bpm.prepare_games(all_rows[season], season, games, replay)
    keep_days = set(sorted({g["date"] for g in sg})[:days_limit]) if days_limit else None
    cum = defaultdict(lambda: defaultdict(float))          # Team -> Spieler -> Minuten (laufende Saison, Spiele vor dem Tag)
    last_players = {}                                      # Team -> Spieler mit Minuten im vorigen Teamspiel
    team_gp = defaultdict(int)
    pending, cur_day = [], None
    n_games = len(sg)
    R, T = defaultdict(list), defaultdict(list)
    PA, PB, PC = [], [], []

    def flush():
        for g_ in pending:
            for r_ in g_["rows"]:
                if r_["minutes"] > 0:
                    cum[r_["team"]][r_["person_id"]] += r_["minutes"]
            for tm in (g_["home"], g_["away"]):
                last_players[tm] = {r_["person_id"] for r_ in g_["rows"] if r_["team"] == tm and r_["minutes"] > 0}
        pending.clear()

    def next_team(pid, day, gid):
        """Team des naechsten Einsatzes (Minuten > 0) nach diesem Spiel; None, wenn keiner."""
        for r in store.by_player.get(pid, []):
            if (r["date"], r["game_id"]) > (day, gid) and r["minutes"] > 0:
                return r["team"]
        return None

    n_tg = 0
    for gi, g in enumerate(sg):
        if g["date"] != cur_day:
            flush()
            cur_day = g["date"]
        gp_by = {"home": team_gp[g["home"]], "away": team_gp[g["away"]]}
        team_gp[g["home"]] += 1; team_gp[g["away"]] += 1
        pending.append(g)
        if keep_days is not None and g["date"] not in keep_days:
            continue
        day = g["date"]
        adapter.set_day(day, (g["home"], g["away"]))
        for side, team, is_home in (("home", g["home"], True), ("away", g["away"], False)):
            if gp_by[side] < MIN_TEAM_GAMES:
                continue
            played_rows = [r for r in g["rows"] if r["team"] == team and r["minutes"] > 0]
            if not played_rows:
                continue
            played = {r["person_id"] for r in played_rows}
            order = sorted(cum[team].items(), key=lambda kv: (-kv[1], kv[0]))
            rank = {p: i + 1 for i, (p, _) in enumerate(order)}
            absent, absent_rank, fresh = [], [], []
            for p, rk in rank.items():
                if rk > TOP_N:
                    break
                if p in played:
                    continue
                nt = next_team(p, day, g["game_id"])
                if nt is not None and nt != team:
                    continue                                             # Transfer, kein Ausfall
                absent.append(p); absent_rank.append(rk); fresh.append(int(p in last_players.get(team, set())))
            ctx = g["ctx"]
            spread = ctx["exp_spread"]
            B = pf.team_match(team, is_home, ctx, day, None, None)
            C = pf.team_match(team, is_home, ctx, day, None, set(absent)) if absent else B
            # Prognose der Ausgefallenen (roh)
            fmin = fpts = 0.0
            for p in absent:
                fa = B["raw"].get(p) or adapter.forecast_player(p, day, home=is_home, exp_spread=spread, exp_total=ctx.get("exp_total"), name=store.names(p))
                if fa["ok"]:
                    fmin += fa["minutes"]["mean"]; fpts += fa["expected_points"]
            tgi = n_tg; n_tg += 1
            T["tg"].append(tgi); T["gi"].append(gi); T["side"].append(int(is_home)); T["n_abs"].append(len(absent)); T["abs_top3"].append(int(any(r <= 3 for r in absent_rank)))
            T["abs_fresh"].append(int(any(fresh))); T["F_min"].append(fmin); T["F_pts"].append(fpts)
            for r in played_rows:
                pid = r["person_id"]
                raw = B["raw"].get(pid) or adapter.forecast_player(pid, day, home=is_home, exp_spread=spread, exp_total=ctx.get("exp_total"), name=r["name"])
                if not raw["ok"]:
                    continue
                aB = B["adjusted"].get(pid)
                rawC = C["raw"].get(pid) or raw
                aC = C["adjusted"].get(pid)
                fB = aB or raw; fC = aC or rawC
                R["tg"].append(tgi); R["gi"].append(gi); R["date"].append(int(day.replace("-", ""))); R["home"].append(int(is_home)); R["half"].append(int(gi >= n_games // 2))
                R["pid"].append(pid); R["min"].append(r["minutes"]); R["pts"].append(r["points"]); R["rank"].append(rank.get(pid, 99))
                R["emin_A"].append(raw["minutes"]["mean"]); R["epts_A"].append(raw["expected_points"])
                R["emin_B"].append(fB["minutes"]["mean"]); R["epts_B"].append(fB["expected_points"])
                R["emin_C"].append(fC["minutes"]["mean"]); R["epts_C"].append(fC["expected_points"])
                R["spread"].append(spread if is_home else -spread)
                PA.append(p_array(raw).astype(np.float32)); PB.append(p_array(fB).astype(np.float32)); PC.append(p_array(fC).astype(np.float32))
    arr = {"r_" + k: np.asarray(v) for k, v in R.items()}
    arr.update({"t_" + k: np.asarray(v) for k, v in T.items()})
    arr["pA"], arr["pB"], arr["pC"] = np.asarray(PA), np.asarray(PB), np.asarray(PC)
    arr["n_games_total"] = np.array([n_games])
    # naiver Saisonschnitt der Punkte (fuer Linien rund um den Spielerschnitt)
    arr["r_naive"] = np.array([np.nan if (x := bpm.naive_mu(store, int(p), str(d)[:4] + "-" + str(d)[4:6] + "-" + str(d)[6:])) is None else x for p, d in zip(arr["r_pid"], arr["r_date"])])
    if not days_limit:
        np.savez_compressed(TMP / f"{season}.npz", **arr)
    return season, len(arr["r_gi"]), len(arr["t_tg"]), time.time() - t0


def replays(pilot=False):
    if pilot:
        print(run_task(("2025-26", 25)))
        return
    t0 = time.time()
    with Pool(2, maxtasksperchild=1) as pool:
        for res in pool.imap_unordered(run_task, [(s, 0) for s in SEASONS if not (TMP / f"{s}.npz").exists()]):
            print(f"fertig {res[0]}: {res[1]} Spielerzeilen, {res[2]} Team-Spiele, {res[3]:.0f} s (gesamt {time.time() - t0:.0f} s)", flush=True)


if __name__ == "__main__":
    if "--pilot" in sys.argv:
        replays(True)
    elif "--analysis-only" not in sys.argv:
        replays()
        print("Replays fertig")

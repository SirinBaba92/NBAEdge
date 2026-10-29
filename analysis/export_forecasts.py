"""
Rueckgerechnete Prognosen dauerhaft exportieren (Spieler und Teams, 2023-24 bis 2025-26) nach <pbp-dir>/derived (ausserhalb des Projekts). NEU, nur Rechnen und Kopieren, kein Netz,
aendert keine bestehende Datei.

Quellen (nichts neu erfunden)
- Spieler: die Zwischenstaende des Spieler-Backtests analysis/backtest_player_minutes.py (Walk-forward ueber analysis/bt_player_adapter.py: Verlauf nur vor dem Spieltag), Datei <Saison>_base.npz,
  gesichert unter <pbp-dir>/derived/spielerprognosen_roh/pm/. A = roh, B = Teamabgleich ohne Ausfaelle (Teampunkte aus dem kausalen Team-Replay), tspread = erwarteter Abstand dieses Replays AUS SICHT DES SPIELERTEAMS (positiv = Team staerker; Heimteam +Abstand, Gast -Abstand), auf 0,1 gerundet.
  Gespeichert sind nur Spielerzeilen mit Prognose UND Minuten > 0.
- Teams: analysis/backtest_team_markets.py (btm.PRODUCTION) -> analysis/replica_tunable.run: kausaler Walk-forward-Replay ueber alle Spiele ab 2015, REINES MODELL ohne Marktanteil (weder Spread 25 %
  noch Total 32-55 %), unabgerundet. Erwartete Teampunkte: Heim = (Total + Abstand) / 2, Gast = (Total - Abstand) / 2 (wie btm.prepare). Nur Regular Season.
- Verbindung: Spiel-ID und Team ueber (Spieler-ID, Datum) aus data/cache/*player_games*.json (Spieler); Spiele der Teams ueber (Datum, beide Teams) ebenfalls aus diesen Spielerzeilen.
Ausgabe: forecast_players_<Saison>.csv.gz, forecast_teams_<Saison>.csv.gz, export_forecasts_bericht.txt.
Start:  venv/bin/python analysis/export_forecasts.py            (alle drei Saisons)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
LOCAL_FILES = {"2023-24": "backtest_player_games_2023-24.json", "2024-25": "backtest_player_games_2024-25.json", "2025-26": "player_games_2025-26.json"}
PLAYER_COLS = ["spiel_id", "datum", "team", "spieler_id", "minuten_ist", "punkte_ist", "minuten_erw_roh", "punkte_erw_roh", "minuten_erw_teamabgleich", "punkte_erw_teamabgleich", "tspread", "rotation"]
TEAM_COLS = ["spiel_id", "datum", "heim", "gast", "abstand_erw", "total_erw", "punkte_erw_heim", "punkte_erw_gast", "punkte_ist_heim", "punkte_ist_gast"]


def year_of(season: str) -> int:
    return int(season[:4])


def date_int(text: str) -> int:
    return int(str(text)[:10].replace("-", ""))


def fnum(x, d: int = 4):
    """Zahl fuer die CSV: Rundung, NaN/None leer."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    return "" if math.isnan(x) else ("%d" % x if x == int(x) and abs(x) < 1e12 else repr(round(x, d)))


# ----------------------------------------------------------------------------- lokale Spielerdaten
def load_local_rows(season: str, cache_dir: Path | None = None) -> list[dict]:
    return json.loads(((cache_dir or ROOT / "data" / "cache") / LOCAL_FILES[season]).read_text(encoding="utf-8")).get("rows", [])


def index_local(rows: list[dict]) -> dict:
    """{'by_player': {(person_id, datum_int): Zeile}, 'games': {(datum_int, frozenset{Team, Gegner}): spiel_id}, 'team_pts': {(spiel_id, Team): Summe der Spielerpunkte}}."""
    by_player, games, team_pts = {}, {}, defaultdict(int)
    for r in rows:
        d = date_int(r["date"])
        by_player[(int(r["person_id"]), d)] = r
        games[(d, frozenset((r["team"], r["opponent"])))] = str(r["game_id"])
        team_pts[(str(r["game_id"]), r["team"])] += int(r.get("points") or 0)
    return {"by_player": by_player, "games": games, "team_pts": dict(team_pts)}


# ----------------------------------------------------------------------------- Spieler
def players_table(arr: dict, idx: dict) -> tuple[list[list], Counter]:
    """Zeilen der Spieler-CSV (PLAYER_COLS) aus den Feldern der npz-Datei (pid, date, min, pts, emin_A, epts_A, emin_B, epts_B, tspread, in_rot) und dem lokalen Index.
    Rueckgabe (Zeilen, Zaehler {'zeilen', 'geloest', 'min_abweichung', 'pkt_abweichung'})."""
    rows, c = [], Counter()
    n = len(arr["pid"])
    for i in range(n):
        c["zeilen"] += 1
        pid, d = int(arr["pid"][i]), int(arr["date"][i])
        loc = idx["by_player"].get((pid, d))
        if loc is None:
            continue
        c["geloest"] += 1
        if abs(float(loc.get("minutes") or 0) - float(arr["min"][i])) > 1e-9:
            c["min_abweichung"] += 1
        if int(loc.get("points") or 0) != int(arr["pts"][i]):
            c["pkt_abweichung"] += 1
        rows.append([str(loc["game_id"]), "%04d-%02d-%02d" % (d // 10000, d // 100 % 100, d % 100), loc["team"], pid, fnum(arr["min"][i]), fnum(arr["pts"][i]),
                     fnum(arr["emin_A"][i]), fnum(arr["epts_A"][i]), fnum(arr["emin_B"][i]), fnum(arr["epts_B"][i]), fnum(arr["tspread"][i]), int(arr["in_rot"][i])])
    return rows, c


# ----------------------------------------------------------------------------- Teams
def teams_table(games: list[dict], res: dict, season_year: int, idx: dict, elo_factor: float) -> tuple[list[list], Counter, list]:
    """Zeilen der Team-CSV (TEAM_COLS) fuer die Regular-Season-Spiele der Saison aus dem Replay (res: Spalten season, diff, total_pred, margin, total, post je Spiel in games).
    Rueckgabe (Zeilen, Zaehler, Liste (spiel_id, Heim, Gast, mu_s) fuer die Pruefung)."""
    rows, c, info = [], Counter(), []
    for i in range(len(games)):
        if int(res["season"][i]) != season_year or int(res["post"][i]) != 0:
            continue
        g = games[i]
        home, away, d = g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"], date_int(g["date"])
        c["spiele"] += 1
        gid = idx["games"].get((d, frozenset((home, away))), "")
        c["verbunden" if gid else "ohne_spiel_id"] += 1
        mu_s = float(res["diff"][i]) / elo_factor
        mu_t = float(res["total_pred"][i])
        margin, total = float(res["margin"][i]), float(res["total"][i])
        rows.append([gid, "%04d-%02d-%02d" % (d // 10000, d // 100 % 100, d % 100), home, away, fnum(mu_s), fnum(mu_t), fnum((mu_t + mu_s) / 2), fnum((mu_t - mu_s) / 2),
                     fnum((total + margin) / 2), fnum((total - margin) / 2)])
        info.append((gid, home, away, mu_s))
    return rows, c, info


def check_team_points(team_rows: list[list], idx: dict) -> list[str]:
    """Plausibilitaet: tatsaechliche Teampunkte der Team-CSV gegen die Summe der Spielerpunkte je Team und Spiel (lokale Spielerdaten). Liste der Abweichungen (Text)."""
    bad = []
    for r in team_rows:
        gid, home, away, ph, pa = r[0], r[2], r[3], float(r[8]), float(r[9])
        if not gid:
            continue
        for team, pts in ((home, ph), (away, pa)):
            s = idx["team_pts"].get((gid, team))
            if s is None or abs(s - pts) > 1e-9:
                bad.append(f"{gid} {team}: Spielerdaten {s}, Spielstand {pts:g}")
    return bad


def tspread_diffs(player_rows: list[list], info: list) -> list[float]:
    """|tspread - erwarteter Abstand aus Sicht des Spielerteams| je Spielerzeile (Heimteam: +Abstand, Gast: -Abstand); Zeilen ohne verbundenes Teamspiel entfallen."""
    by_game = {gid: (home, mu) for gid, home, _, mu in info if gid}
    out = []
    for r in player_rows:
        g = by_game.get(r[0])
        if g is None or r[10] == "":
            continue
        out.append(abs(float(r[10]) - (g[1] if r[2] == g[0] else -g[1])))
    return out


def write_csv(path: Path, head: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)
    tmp.replace(path)


# ----------------------------------------------------------------------------- Lauf
def run(pbp_dir: Path, seasons=SEASONS, cache_dir: Path | None = None, write=print) -> str:
    import numpy as np
    sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
    import backtest_team_markets as btm                                  # btm.PRODUCTION, btm.load_games, btm.rt (replica_tunable)
    from config.settings import ELO_TO_SPREAD_FACTOR
    out_dir = pbp_dir / "derived"
    npz_dir = out_dir / "spielerprognosen_roh" / "pm"
    lines = ["Export der rueckgerechneten Prognosen (analysis/export_forecasts.py)", ""]
    games = btm.load_games(2015, 2025)
    res, _, _, _ = btm.rt.run(games, **btm.PRODUCTION)                   # kausaler Replay, reines Modell
    write(f"Team-Replay fertig: {len(games)} Spiele")
    for s in seasons:
        idx = index_local(load_local_rows(s, cache_dir))
        lines.append(f"=== {s} ===")
        p = npz_dir / f"{s}_base.npz"
        d = np.load(p)
        arr = {k: d[k] for k in ("pid", "date", "min", "pts", "emin_A", "epts_A", "emin_B", "epts_B", "tspread", "in_rot")}
        prow, pc = players_table(arr, idx)
        write_csv(out_dir / f"forecast_players_{s}.csv.gz", PLAYER_COLS, prow)
        trow, tc, info = teams_table(games, res, year_of(s), idx, ELO_TO_SPREAD_FACTOR)
        write_csv(out_dir / f"forecast_teams_{s}.csv.gz", TEAM_COLS, trow)
        n_games_p = len({r[0] for r in prow})
        lines += [f"Spieler: {pc['zeilen']} Zeilen, mit Spiel-ID und Team verbunden {pc['geloest']} ({100 * pc['geloest'] / max(1, pc['zeilen']):.2f} %), Spiele darin: {n_games_p}",
                  f"  Abweichung der tatsaechlichen Minuten / Punkte gegen die lokalen Spielerdaten: {pc['min_abweichung']} / {pc['pkt_abweichung']} Zeilen",
                  f"Teams: {tc['spiele']} Regular-Season-Spiele im Replay, mit Spiel-ID verbunden {tc['verbunden']} ({100 * tc['verbunden'] / max(1, tc['spiele']):.2f} %), ohne Spiel-ID {tc['ohne_spiel_id']}"]
        local_games = len({g for g in idx["games"].values()})
        lines.append(f"  Spiele in den lokalen Spielerdaten: {local_games}; Spiele mit Spielerprognosen: {n_games_p} (fehlen: {local_games - n_games_p})")
        bad = check_team_points(trow, idx)
        lines.append(f"Plausibilitaet: Teampunkte aus der Summe der Spielerpunkte gegen die tatsaechlichen Teampunkte in forecast_teams: {len(bad)} Abweichungen von {2 * tc['verbunden']} Teams" + ("" if not bad else " (z. B. " + "; ".join(bad[:5]) + ")"))
        diffs = tspread_diffs(prow, info)
        lines.append(f"  tspread der Spieler-Datei (Abstand aus Sicht des Spielerteams, positiv = Team staerker, auf 0,1 gerundet) gegen den Abstand des Team-Replays: groesste Abweichung "
                     f"{max(diffs) if diffs else float('nan'):.3f} (Rundung erlaubt 0,05), Zeilen darueber: {sum(1 for x in diffs if x > 0.0501)} von {len(diffs)}")
        lines.append("")
        write(f"{s}: Spieler {pc['geloest']}/{pc['zeilen']}, Teams {tc['verbunden']}/{tc['spiele']}")
    text = "\n".join(lines) + "\n"
    (out_dir / "export_forecasts_bericht.txt").write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--seasons", nargs="+", default=list(SEASONS), choices=list(SEASONS))
    args = ap.parse_args(argv)
    print(run(Path(args.pbp_dir), tuple(args.seasons)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Experiment 5.1, Stufe 1: Punkte pro Minute zerlegen (Wuerfe pro Minute x Punkte pro Wurf). Nur Analyse, kein Netz; das Spielerpunkte-Modell (engine/player_forecast.py) und alle bestehenden Dateien bleiben unveraendert.
Schreibt analysis/results/ppm_decomposition.txt.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/ppm_decomposition.py

ENTSCHEIDUNGSREGEL (vorab festgelegt, vor der Auswertung): Eine Variante zaehlt als besser, wenn sie in ALLEN DREI Testsaisons in der Gruppe 1 bis 9 bisherige Spiele den mittleren quadratischen Fehler gegenueber R senkt
und in der Gruppe ab 30 bisherigen Spielen nicht verschlechtert (ebenfalls in allen drei Saisons). Die Parameter (k, k_min) werden nur aus den zwei Trainingssaisons gewaehlt und auf der dritten getestet (alle drei Kombinationen).
Auswahlregel der Parameter (je Fenster 'alle Spiele' / 'letzte 20'): unter den Kombinationen, die in der Trainingsgruppe ab 30 Spielen den Fehler gegenueber R nicht erhoehen, die mit dem kleinsten mittleren quadratischen Fehler in der
Trainingsgruppe 1 bis 9; gibt es keine solche, die mit dem kleinsten Fehler in der Gruppe 1 bis 9 (im Bericht vermerkt).

Daten
- Spielerzeilen mit Minuten, Punkten, Wuerfen (FGA, FGM, 3PA, 3PM, FTA, FTM) aus data/cache (backtest_player_games_2023-24, backtest_player_games_2024-25, player_games_2025-26); die Wuerfe stehen dort schon je Spieler und Spiel.
  Pruefung 1: 2*FGM + 3PM + FTM gegen Punkte (lokal). Pruefung 2: dieselben Wuerfe aus dem Play-by-Play (<pbp-dir>/<Saison>/<id>.json.gz, nur gelesen) gegen die lokalen Werte.
- Prognosen: <pbp-dir>/derived/forecast_players_<Saison>.csv.gz (erwartete Punkte roh, erwartete Minuten roh, Minuten/Punkte tatsaechlich); Verbindung ueber Spieler-ID und Datum (wie export_forecasts.py).
- Spiel 0022400061 ausgeschlossen (Auswertung und Verlauf); Verlaengerungsspiele (Teamsumme der Spielerminuten > 245) in der Auswertung ausgeschlossen, im Verlauf enthalten.
Varianten (Verlauf = alle Spiele des Spielers mit Minuten > 0 und Datum VOR dem Spieltag, ueber Saisongrenzen, ab 2023-24; einfacher Mittelwert, keine Zeitgewichtung)
- R:  bisherige erwartete Punkte roh.
- S:  erwartete Minuten roh x (FGA/Min x Punkte/FGA + FTA/Min x Punkte/FTA). FGA/Min und FTA/Min = Summe der Versuche / Summe der Minuten im Verlauf, mit Richtung Ligamittel gezogen: (m r + k_min L) / (m + k_min),
  m = Minuten im Verlauf, k_min aus {100, 200, 400}. Punkte/FGA = (2 FGM + 3PM) / FGA, Punkte/FTA = FTM / FTA, jeweils (n e + k Le) / (n + k), n = Versuche des Spielers, k aus {25, 50, 100, 200} (gleiches k fuer FG und FT).
  Ligamittel aus allen Spielerzeilen vor dem Spieltag. Fenster: alle Spiele vor dem Spieltag oder die letzten 20. S0 = ohne Zug zum Ligamittel (k = 0, k_min = 0) als Bezug.
"""
import argparse
import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from analysis import build_lineups as bl  # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
LOCAL = {"2023-24": "backtest_player_games_2023-24.json", "2024-25": "backtest_player_games_2024-25.json", "2025-26": "player_games_2025-26.json"}
EXCLUDED_GAME = "0022400061"
OT_MINUTES = 245.0
STARTER_MIN = 28.0
KS = (25, 50, 100, 200)
KMINS = (100, 200, 400)
WINDOWS = ("alle", "l20")
LAST_N = 20
GROUPS = ("1-9 Spiele", "10-29 Spiele", "ab 30 Spiele", "Starter")
OUT = HERE / "results" / "ppm_decomposition.txt"


def date_int(text) -> int:
    return int(str(text)[:10].replace("-", ""))


# ----------------------------------------------------------------------------- lokale Daten und Pruefungen
def load_local(cache_dir: Path) -> list[dict]:
    out = []
    for s in SEASONS:
        for r in json.loads((cache_dir / LOCAL[s]).read_text(encoding="utf-8"))["rows"]:
            if str(r["game_id"]) == EXCLUDED_GAME:
                continue
            out.append(r)
    return out


def check_local_points(rows: list[dict]) -> dict:
    bad = [r for r in rows if 2 * r["fgm"] + r["fg3m"] + r["ftm"] != r["points"]]
    return {"zeilen": len(rows), "abweichend": len(bad), "max_abw": max((abs(2 * r["fgm"] + r["fg3m"] + r["ftm"] - r["points"]) for r in bad), default=0)}


def pbp_shots(actions: list[dict]) -> dict:
    """{personId: [fga, fgm, fg3a, fg3m, fta, ftm]} aus dem Play-by-Play."""
    out = defaultdict(lambda: [0] * 6)
    for a in actions:
        t = str(a.get("actionType"))
        pid = bl.to_int(a.get("personId"))
        res = str(a.get("shotResult") or "")
        if not pid or t not in ("2pt", "3pt", "freethrow") or res not in ("Made", "Missed"):
            continue
        m = res == "Made"
        o = out[pid]
        if t == "freethrow":
            o[4] += 1; o[5] += m
        else:
            o[0] += 1; o[1] += m
            if t == "3pt":
                o[2] += 1; o[3] += m
    return out


def compare_pbp(rows: list[dict], pbp_dir: Path, seasons=SEASONS) -> dict:
    """Je Saison: Spiele verglichen, Spielerzeilen verglichen / mit Abweichung, Summe 2*FGM+3PM+FTM aus dem PBP gegen die lokalen Punkte."""
    by_game = defaultdict(dict)
    for r in rows:
        by_game[(r["season"], str(r["game_id"]))][int(r["person_id"])] = r
    res = {}
    for s in seasons:
        c = {"spiele": 0, "ohne_pbp": 0, "zeilen": 0, "abweichend": 0, "pbp_pkt_abw": 0, "fehlend_lokal": 0}
        for (ss, gid), players in by_game.items():
            if ss != s:
                continue
            r = bl.read_pbp(pbp_dir / s / f"{gid}.json.gz")
            if r is None:
                c["ohne_pbp"] += 1
                continue
            c["spiele"] += 1
            shots = pbp_shots(r[1])
            for pid, v in shots.items():
                loc = players.get(pid)
                if loc is None:
                    if any(v):
                        c["fehlend_lokal"] += 1
                    continue
                c["zeilen"] += 1
                want = [loc["fga"], loc["fgm"], loc["fg3a"], loc["fg3m"], loc["fta"], loc["ftm"]]
                c["abweichend"] += list(map(int, v)) != want
                c["pbp_pkt_abw"] += (2 * v[1] + v[3] + v[5]) != loc["points"]
        res[s] = c
    return res


# ----------------------------------------------------------------------------- Verlauf
class History:
    """Kumulierte Summen je Spieler (nach Datum) und fuer die Liga; Zugriff 'vor Datum D'."""
    FIELDS = ("min", "fga", "ptsfg", "fta", "ftm", "n")

    def __init__(self, rows: list[dict]):
        per = defaultdict(list)
        for r in rows:
            if r["minutes"] > 0:
                per[int(r["person_id"])].append(r)
        self.dates, self.cum = {}, {}
        for pid, lst in per.items():
            lst.sort(key=lambda r: (date_int(r["date"]), str(r["game_id"])))
            self.dates[pid] = np.array([date_int(r["date"]) for r in lst])
            self.cum[pid] = np.vstack([np.zeros(6), np.cumsum([self.vec(r) for r in lst], axis=0)])
        day = defaultdict(lambda: np.zeros(6))
        for lst in per.values():
            for r in lst:
                day[date_int(r["date"])] += self.vec(r)
        self.ldates = np.array(sorted(day))
        self.lcum = np.vstack([np.zeros(6), np.cumsum([day[d] for d in self.ldates], axis=0)])

    @classmethod
    def vec(cls, r: dict) -> np.ndarray:
        return np.array([r["minutes"], r["fga"], 2 * r["fgm"] + r["fg3m"], r["fta"], r["ftm"], 1.0])

    def player(self, pid: int, day: int, window: str) -> np.ndarray:
        """Summen (min, fga, ptsfg, fta, ftm, n) der Spiele VOR day; window 'alle' oder 'l20'."""
        if pid not in self.dates:
            return np.zeros(6)
        k = int(np.searchsorted(self.dates[pid], day, side="left"))            # Spiele mit Datum < day
        lo = 0 if window == "alle" else max(0, k - LAST_N)
        return self.cum[pid][k] - self.cum[pid][lo]

    def league(self, day: int) -> np.ndarray:
        return self.lcum[int(np.searchsorted(self.ldates, day, side="left"))]


def predict(agg: np.ndarray, lg: np.ndarray, emin: np.ndarray, k: float, kmin: float) -> np.ndarray:
    """agg [Zeilen, 6] (min, fga, ptsfg, fta, ftm, n) des Spielers, lg [Zeilen, 6] Liga, emin erwartete Minuten roh -> erwartete Punkte S."""
    m, fga, ptsfg, fta, ftm = agg[:, 0], agg[:, 1], agg[:, 2], agg[:, 3], agg[:, 4]
    L_fga, L_fta = lg[:, 1] / lg[:, 0], lg[:, 3] / lg[:, 0]
    L_pfg, L_pft = lg[:, 2] / lg[:, 1], lg[:, 4] / lg[:, 3]
    r_fga = (fga + kmin * L_fga) / (m + kmin)                                  # = (m r + kmin L) / (m + kmin) mit r = fga / m
    r_fta = (fta + kmin * L_fta) / (m + kmin)
    with np.errstate(invalid="ignore", divide="ignore"):
        e_fg = np.where(fga > 0, ptsfg / np.maximum(fga, 1e-12), L_pfg)
        e_ft = np.where(fta > 0, ftm / np.maximum(fta, 1e-12), L_pft)
    pp_fg = (fga * e_fg + k * L_pfg) / (fga + k) if k > 0 else e_fg
    pp_ft = (fta * e_ft + k * L_pft) / (fta + k) if k > 0 else e_ft
    if kmin == 0:
        r_fga, r_fta = fga / np.maximum(m, 1e-12), fta / np.maximum(m, 1e-12)
    return emin * (r_fga * pp_fg + r_fta * pp_ft)


# ----------------------------------------------------------------------------- Zeilen
def load_forecast_rows(pbp_dir: Path, season: str) -> list[dict]:
    rows, tot = [], defaultdict(float)
    with gzip.open(pbp_dir / "derived" / f"forecast_players_{season}.csv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["spiel_id"] == EXCLUDED_GAME:
                continue
            try:
                row = {"season": season, "game": r["spiel_id"], "team": r["team"], "pid": int(r["spieler_id"]), "day": date_int(r["datum"]), "emin": float(r["minuten_erw_roh"]),
                       "epts": float(r["punkte_erw_roh"]), "act": float(r["punkte_ist"]), "mact": float(r["minuten_ist"])}
            except ValueError:
                continue
            tot[(row["game"], row["team"])] += row["mact"]
            rows.append(row)
    for r in rows:
        r["ot"] = tot[(r["game"], r["team"])] > OT_MINUTES
    return rows


def build_table(rows: list[dict], hist: History) -> dict:
    """Arrays je Zeile: Verlauf (beide Fenster), Liga, Gruppen. Zeilen ohne bisheriges Spiel werden verworfen (Zaehler 'ohne_verlauf')."""
    keep, agg, lg = [], {w: [] for w in WINDOWS}, []
    for r in rows:
        a = hist.player(r["pid"], r["day"], "alle")
        l = hist.league(r["day"])
        if a[5] < 1 or l[0] <= 0:
            continue
        keep.append(r)
        agg["alle"].append(a); agg["l20"].append(hist.player(r["pid"], r["day"], "l20")); lg.append(l)
    T = {"rows": keep, "agg": {w: np.array(v) for w, v in agg.items()}, "lg": np.array(lg), "ohne_verlauf": len(rows) - len(keep),
            "season": np.array([r["season"] for r in keep]), "emin": np.array([r["emin"] for r in keep]), "epts": np.array([r["epts"] for r in keep]),
            "act": np.array([r["act"] for r in keep]), "ot": np.array([r["ot"] for r in keep])}
    T["ngames"] = T["agg"]["alle"][:, 5]
    return T


def group_masks(ngames: np.ndarray, emin: np.ndarray) -> dict:
    return {"1-9 Spiele": (ngames >= 1) & (ngames <= 9), "10-29 Spiele": (ngames >= 10) & (ngames <= 29), "ab 30 Spiele": ngames >= 30, "Starter": emin > STARTER_MIN}


def err_stats(pred: np.ndarray, act: np.ndarray) -> dict:
    if len(pred) == 0:
        return {"n": 0, "mae": float("nan"), "rmse": float("nan"), "bias": float("nan")}
    e = act - pred
    return {"n": len(e), "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e ** 2).mean())), "bias": float(e.mean())}


def pred_all(T: dict, w: str, k: float, kmin: float) -> np.ndarray:
    return predict(T["agg"][w], T["lg"], T["emin"], k, kmin)


def choose_params(T: dict, train_seasons, w: str) -> tuple:
    """(k, kmin, Hinweis) nach der vorab festgelegten Auswahlregel, nur aus den Trainingssaisons (ohne Verlaengerungsspiele)."""
    base = np.isin(T["season"], list(train_seasons)) & ~T["ot"]
    gm = group_masks(T["ngames"], T["emin"])
    g_lo, g_hi = base & gm["1-9 Spiele"], base & gm["ab 30 Spiele"]
    r_hi = err_stats(T["epts"][g_hi], T["act"][g_hi])["rmse"]
    cands = []
    for k in KS:
        for kmin in KMINS:
            p = pred_all(T, w, k, kmin)
            cands.append((k, kmin, err_stats(p[g_lo], T["act"][g_lo])["rmse"], err_stats(p[g_hi], T["act"][g_hi])["rmse"]))
    ok = [c for c in cands if c[3] <= r_hi]
    pool, note = (ok, "") if ok else (cands, "keine Kombination hielt ab 30 Spielen den Fehler von R (im Training); nur Gruppe 1-9 entschied")
    best = min(pool, key=lambda c: c[2])
    return best[0], best[1], note


def decide(res: dict) -> dict:
    """res[variante][saison][gruppe] -> Stats; R unter 'R'. Regel: in allen Saisons 1-9 RMSE < R und ab 30 RMSE <= R."""
    out = {}
    for v, per in res.items():
        if v == "R":
            continue
        low = all(per[s]["1-9 Spiele"]["rmse"] < res["R"][s]["1-9 Spiele"]["rmse"] for s in per)
        high = all(per[s]["ab 30 Spiele"]["rmse"] <= res["R"][s]["ab 30 Spiele"]["rmse"] for s in per)
        out[v] = {"1-9 besser in allen Saisons": low, "ab 30 nicht schlechter in allen Saisons": high, "Regel erfuellt": low and high}
    return out


# ----------------------------------------------------------------------------- Bericht
def fmt_row(st) -> str:
    return f"{st['n']:>7d} {st['mae']:>7.3f} {st['rmse']:>7.3f} {st['bias']:>+7.3f}"


def build_report(T: dict, checks: dict, pbp_cmp: dict, notes: list) -> str:
    out = ["Punkte pro Minute zerlegen (Stufe 1): R gegen S = erwartete Minuten x Wuerfe/Minute x Punkte/Wurf (beschreibend; die Entscheidungsregel steht unten)",
           "Verlauf: alle Spiele vor dem Spieltag (Mittelwert ohne Zeitgewichtung) oder die letzten 20. Gruppen nach Zahl bisheriger Spiele (alle Saisons zusammen gezaehlt) und Starter (erwartete Minuten roh > 28).",
           "Spalten: Zeilen / mittlerer absoluter Fehler (MAE) / Wurzel des mittleren quadratischen Fehlers (RMSE) / Verzerrung (tatsaechlich minus erwartet). Ohne Verlaengerungsspiele und ohne Spiel 0022400061.", "",
           "VORAB FESTGELEGTE ENTSCHEIDUNGSREGEL: Eine Variante zaehlt als besser, wenn sie in allen drei Testsaisons in der Gruppe 1-9 Spiele den quadratischen Fehler gegenueber R senkt und in der Gruppe ab 30 Spielen nicht verschlechtert.",
           "Parameter (k, k_min) je Fenster nur aus zwei Saisons gewaehlt (kleinster RMSE in Gruppe 1-9, Nebenbedingung: ab 30 Spielen nicht schlechter als R), getestet auf der dritten.", "", "0. DATENPRUEFUNG",
           f"  Lokal: 2*FGM + 3PM + FTM gegen Punkte: {checks['zeilen']} Spielerzeilen, {checks['abweichend']} abweichend (max. Abweichung {checks['max_abw']} Punkte)."]
    for s, c in pbp_cmp.items():
        out.append(f"  Play-by-Play {s}: {c['spiele']} Spiele verglichen ({c['ohne_pbp']} ohne lesbare Datei), {c['zeilen']} Spielerzeilen mit Wuerfen; Wurfzahlen weichen bei {c['abweichend']} ab; "
                   f"Punkte aus PBP-Wuerfen weichen bei {c['pbp_pkt_abw']} von den lokalen Punkten ab; Spieler im PBP ohne lokale Zeile: {c['fehlend_lokal']}.")
    out += ["", f"Zeilen mit Prognose ohne bisheriges Spiel (nicht auswertbar): {T['ohne_verlauf']}.", ""]
    return "\n".join(out + notes) + "\n"


def run(pbp_dir: Path, cache_dir: Path, seasons=SEASONS, write=print, check_pbp: bool = True) -> str:
    local = load_local(cache_dir)
    checks = check_local_points(local)
    pbp_cmp = compare_pbp(local, pbp_dir, seasons) if check_pbp else {}
    hist = History(local)
    rows = [r for s in seasons for r in load_forecast_rows(pbp_dir, s)]
    T = build_table(rows, hist)
    gm = group_masks(T["ngames"], T["emin"])
    evalm = ~T["ot"]
    res, params, notes = {}, {}, []
    names = {"R": None, "S0 alle": ("alle", 0, 0), "S0 l20": ("l20", 0, 0)}
    for w in WINDOWS:
        names[f"S_best {w}"] = ("best", w)
    for v in names:
        res[v] = {}
    for test in seasons:
        train = [s for s in seasons if s != test]
        sm = (T["season"] == test) & evalm
        for v, spec in names.items():
            if spec is None:
                p = T["epts"]
            elif spec[0] == "best":
                k, kmin, note = choose_params(T, train, spec[1])
                params[(test, spec[1])] = (k, kmin, note)
                p = pred_all(T, spec[1], k, kmin)
            else:
                p = pred_all(T, spec[0], spec[1], spec[2])
            res[v][test] = {g: err_stats(p[sm & gm[g]], T["act"][sm & gm[g]]) for g in GROUPS}
    # Gesamt ueber die drei Testsaisons
    out = [build_report(T, checks, pbp_cmp, [])]
    out.append("1. AUSGEWAEHLTE PARAMETER (aus den zwei Trainingssaisons)")
    for (test, w), (k, kmin, note) in params.items():
        out.append(f"  Test {test}, Fenster {w}: k = {k}, k_min = {kmin}" + (f"   [{note}]" if note else ""))
    out.append("")
    out.append("2. TABELLEN JE GRUPPE (Zeilen / MAE / RMSE / Verzerrung)")
    for g in GROUPS:
        out.append(f"Gruppe {g}")
        out.append("  " + "Variante".ljust(12) + "".join(f"{s:^26}" for s in seasons))
        for v in names:
            out.append("  " + v.ljust(12) + " | ".join(fmt_row(res[v][s][g]) for s in seasons))
        out.append("")
    dec = decide(res)
    out.append("3. ENTSCHEIDUNGSREGEL (je Variante, mit den aus zwei Saisons gewaehlten Parametern bei S_best)")
    for v, d in dec.items():
        out.append(f"  {v}: 1-9 Spiele besser in allen drei Saisons: {'ja' if d['1-9 besser in allen Saisons'] else 'nein'}; ab 30 Spielen nicht schlechter in allen drei Saisons: {'ja' if d['ab 30 nicht schlechter in allen Saisons'] else 'nein'}; "
                   f"Regel erfuellt: {'JA' if d['Regel erfuellt'] else 'NEIN'}")
    out.append("")
    out.append("4. GANZES GITTER (RMSE je Gruppe und Saison, ohne Auswahl; R zuerst) - zur Einsicht, nicht zur Auswahl")
    for s in seasons:
        sm = (T["season"] == s) & evalm
        out.append(f"Saison {s}: Variante".ljust(26) + "".join(g.rjust(14) for g in GROUPS))
        out.append("  " + "R".ljust(24) + "".join(f"{err_stats(T['epts'][sm & gm[g]], T['act'][sm & gm[g]])['rmse']:>14.3f}" for g in GROUPS))
        for w in WINDOWS:
            for k in KS:
                for kmin in KMINS:
                    p = pred_all(T, w, k, kmin)
                    out.append("  " + f"S {w} k={k} kmin={kmin}".ljust(24) + "".join(f"{err_stats(p[sm & gm[g]], T['act'][sm & gm[g]])['rmse']:>14.3f}" for g in GROUPS))
        out.append("")
    out += ["5. NICHT GEPRUEFT", "  Signifikanz (kein Test, kein Bootstrap); Zeitgewichtung wie im bisherigen Modell; Wirkung auf Chancen/Meilensteine (nicht Teil dieser Stufe); getrennte k fuer Feldwuerfe und Freiwuerfe;",
            "  Verlauf nur ab 2023-24 (2022-23 liegt nicht lokal vor); Spiele 'ohne bisheriges Spiel' fehlen; Parameterauswahl nur nach RMSE der Gruppe 1-9 mit Nebenbedingung ab 30 Spielen."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    text = run(Path(a.pbp_dir), Path(a.cache_dir))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

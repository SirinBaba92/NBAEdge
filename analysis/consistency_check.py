"""
Konsistenzpruefung: Summe der erwarteten Spielerpunkte eines Teams gegen den erwarteten Teampunktestand, und Zusammenhaenge der Prognosefehler zwischen Spielern und Team.
NEU, rein beschreibend (nur Zahlen), kein Netz, aendert keine bestehende Datei.

Eingabe: <pbp-dir>/derived/forecast_players_<Saison>.csv.gz und forecast_teams_<Saison>.csv.gz (analysis/export_forecasts.py). Die Spielerdateien enthalten nur Spieler mit Prognose UND Minuten > 0.
Ausgabe: analysis/results/consistency_check.txt (je Saison und gesamt; getrennt nach Heim und Gast; alle Spiele / ohne / mit Verlaengerung).

Begriffe
- Team und Spiel = eine Zeile je Team; Teampunkte (tatsaechlich) aus forecast_teams, erwartete Teampunkte des Team-Modells (reines Modell, walk-forward) ebenfalls dort.
- Spieler mit Prognose = die Spieler der Spielerdatei. Abdeckung = Summe ihrer tatsaechlichen Punkte / tatsaechliche Teampunkte. A = erwartete Punkte roh, B = mit Teamabgleich (Spieler ausserhalb der Rotation: gleich A).
- Konsistenz (a): Summe der erwarteten Spielerpunkte (A bzw. B) minus erwartete Teampunkte mal mittlere Abdeckung (Mittel der Abdeckung in derselben Gruppe: Saison, Seite, Verlaengerung ja/nein).
  Konsistenz (b): Summe der erwarteten Spielerpunkte minus tatsaechliche Punkte derselben Spieler. Ausgewiesen: mittlerer Unterschied, Streuung (Standardabweichung), Anteil der Spiele mit |Unterschied| > 5 Punkte.
- Fehler = tatsaechlich minus erwartet. Teamfehler = tatsaechliche Teampunkte minus erwartete Teampunkte; Summenfehler der Spieler = tatsaechliche Punkte der Spieler mit Prognose minus Summe A (bzw. B).
  (a) Korrelation (Pearson) von Teamfehler und Summenfehler, getrennt nach Heim/Gast. (b) mittlere paarweise Korrelation der Prognosefehler roh (A) zwischen zwei Spielern desselben Teams im selben Spiel, nur Spieler
  mit mindestens 15 erwarteten Minuten (roh): Fehler werden mit dem gemeinsamen Mittel und der gemeinsamen Standardabweichung der Gruppe standardisiert; Korrelation = Summe aller Paarprodukte
  (je Team und Spiel) / Zahl der Paare (gepoolter Schaetzer, kein Paar wird einzeln ueber die Saison gerechnet). (c) Korrelation von Teamfehler Heim und Teamfehler Gast im selben Spiel.
- Verlaengerung: Summe der tatsaechlichen Minuten der Spieler mit Prognose eines Teams ueber 245 (ein Spiel zaehlt, wenn es fuer eines der beiden Teams zutrifft). Da nicht alle Spieler in der Datei stehen, kann
  eine Verlaengerung unentdeckt bleiben (Zahl der erkannten Spiele steht im Bericht).
- Teamabgleich-Faktor: steht nicht in den Dateien (nur die Ergebnisse A und B); die Haeufigkeit der Grenzen 0,6 und 1,4 laesst sich aus ihnen nicht ermitteln.
Start:  venv/bin/python analysis/consistency_check.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
OT_MINUTES = 245.0
MIN_EXP_MINUTES = 15.0
BIG = 5.0


def load_season(pbp_dir: Path, season: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pbp_dir / "derived"
    return pd.read_csv(d / f"forecast_players_{season}.csv.gz", dtype={"spiel_id": str}), pd.read_csv(d / f"forecast_teams_{season}.csv.gz", dtype={"spiel_id": str})


def team_games(players: pd.DataFrame, teams: pd.DataFrame, season: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(Team-Spiel-Tabelle, Spielertabelle mit Spalten seite/ot/fehler, Zaehler). Eine Zeile je Team und Spiel mit Spielerprognosen und verbundenem Teamspiel."""
    t = teams[teams["spiel_id"].notna() & (teams["spiel_id"] != "")].copy()
    t["spiel_id"] = t["spiel_id"].astype(str)
    side = pd.concat([t[["spiel_id", "heim"]].rename(columns={"heim": "team"}).assign(seite="heim"), t[["spiel_id", "gast"]].rename(columns={"gast": "team"}).assign(seite="gast")])
    p = players.merge(side, on=["spiel_id", "team"], how="inner")
    dropped = len(players) - len(p)
    p["fehler_roh"] = p["punkte_ist"] - p["punkte_erw_roh"]
    g = p.groupby(["spiel_id", "seite"]).agg(team=("team", "first"), n=("spieler_id", "size"), akt_spieler=("punkte_ist", "sum"), summe_a=("punkte_erw_roh", "sum"),
                                              summe_b=("punkte_erw_teamabgleich", "sum"), minuten=("minuten_ist", "sum")).reset_index()
    tt = t.set_index("spiel_id")
    g["akt_team"] = [tt.loc[i, "punkte_ist_heim" if s == "heim" else "punkte_ist_gast"] for i, s in zip(g["spiel_id"], g["seite"])]
    g["erw_team"] = [tt.loc[i, "punkte_erw_heim" if s == "heim" else "punkte_erw_gast"] for i, s in zip(g["spiel_id"], g["seite"])]
    ot = (g["minuten"] > OT_MINUTES).groupby(g["spiel_id"]).transform("max")
    g["ot"] = ot.astype(bool)
    g["saison"] = season
    p = p.merge(g[["spiel_id", "seite", "ot"]], on=["spiel_id", "seite"], how="left")
    p["saison"] = season
    return g, p, {"spieler_zeilen_ohne_teamspiel": int(dropped), "team_spiele": int(len(g)), "spiele_ot": int(g.loc[g["ot"], "spiel_id"].nunique())}


def corr(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def summarize_diff(d) -> dict:
    d = np.asarray(d, float)
    return {"mittel": float(np.mean(d)) if len(d) else float("nan"), "sd": float(np.std(d, ddof=1)) if len(d) > 1 else float("nan"), "anteil_gt5": float(np.mean(np.abs(d) > BIG)) if len(d) else float("nan")}


def pair_corr(p: pd.DataFrame) -> tuple[float, int]:
    """Gepoolte mittlere paarweise Korrelation der Roh-Fehler (siehe Kopf), nur Spieler mit mindestens MIN_EXP_MINUTES erwarteten Minuten. Rueckgabe (Korrelation, Zahl der Paare)."""
    q = p[p["minuten_erw_roh"] >= MIN_EXP_MINUTES]
    if len(q) < 3:
        return float("nan"), 0
    sd = q["fehler_roh"].std(ddof=0)
    if not sd:
        return float("nan"), 0
    z = (q["fehler_roh"] - q["fehler_roh"].mean()) / sd
    grp = z.groupby([q["spiel_id"], q["seite"]])
    s, s2, k = grp.sum(), (z ** 2).groupby([q["spiel_id"], q["seite"]]).sum(), grp.size()
    pairs = (k * (k - 1) / 2).sum()
    return (float(((s ** 2 - s2) / 2).sum() / pairs), int(pairs)) if pairs else (float("nan"), 0)


def group_metrics(g: pd.DataFrame, p: pd.DataFrame) -> dict:
    """Kennzahlen einer Gruppe (Team-Spiel-Zeilen g, Spielerzeilen p) getrennt nach Seite plus Korrelation Heim/Gast (c)."""
    out = {"seite": {}}
    for side in ("heim", "gast"):
        s = g[g["seite"] == side]
        ps = p[p["seite"] == side]
        cov = s["akt_spieler"] / s["akt_team"]
        cov_mean = float(cov.mean()) if len(s) else float("nan")
        m = {"n": int(len(s)), "abdeckung_mittel": cov_mean, "abdeckung_sd": float(cov.std(ddof=1)) if len(s) > 1 else float("nan")}
        for x in ("a", "b"):
            tot = s[f"summe_{x}"]
            m[f"{x}_gegen_team"] = summarize_diff(tot - s["erw_team"] * cov_mean)
            m[f"{x}_gegen_ist"] = summarize_diff(tot - s["akt_spieler"])
            m[f"korr_team_summe_{x}"] = corr(s["akt_team"] - s["erw_team"], s["akt_spieler"] - tot)
        m["paarkorr"], m["paare"] = pair_corr(ps)
        out["seite"][side] = m
    h = g[g["seite"] == "heim"].set_index("spiel_id")
    a = g[g["seite"] == "gast"].set_index("spiel_id")
    both = h.index.intersection(a.index)
    out["korr_heim_gast"] = corr((h.loc[both, "akt_team"] - h.loc[both, "erw_team"]).values, (a.loc[both, "akt_team"] - a.loc[both, "erw_team"]).values)
    out["spiele"] = int(len(both))
    return out


def evaluate(g: pd.DataFrame, p: pd.DataFrame) -> dict:
    return {"alle": group_metrics(g, p), "ohne Verlaengerung": group_metrics(g[~g["ot"]], p[~p["ot"]]), "mit Verlaengerung": group_metrics(g[g["ot"]], p[p["ot"]])}


# ----------------------------------------------------------------------------- Text
def f(x, d=3, signed=False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:+.{d}f}" if signed else f"{x:.{d}f}"


def pc(x) -> str:
    return "-" if x is None or np.isnan(x) else f"{100 * x:.1f} %"


def block_text(title: str, res: dict, info: dict | None = None) -> list[str]:
    lines = [f"--- {title} ---"]
    h, a = res["seite"]["heim"], res["seite"]["gast"]
    lines.append(f"Team-Spiele: Heim {h['n']}, Gast {a['n']} (Spiele mit beiden Seiten: {res['spiele']})")
    row = lambda name, fn: lines.append(f"  {name:<78} Heim {fn(h):<34} Gast {fn(a)}")
    row("1. Abdeckung (Punkte der Spieler mit Prognose / Teampunkte): Mittel (Streuung)", lambda m: f"{pc(m['abdeckung_mittel'])} ({pc(m['abdeckung_sd'])})")
    for x, name in (("a", "A roh"), ("b", "B Teamabgleich")):
        for key, label in (("gegen_team", "gegen erwartete Teampunkte x mittlere Abdeckung"), ("gegen_ist", "gegen tatsaechliche Punkte derselben Spieler")):
            row(f"2. Summe erwartet {name} {label}: Mittel / Streuung / Anteil > 5", lambda m, x=x, key=key: f"{f(m[f'{x}_{key}']['mittel'], 2, True)} / {f(m[f'{x}_{key}']['sd'], 2)} / {pc(m[f'{x}_{key}']['anteil_gt5'])}")
    row("4a. Korrelation Teamfehler und Summenfehler der Spieler (A roh)", lambda m: f(m["korr_team_summe_a"]))
    row("4a. dasselbe mit Teamabgleich (B)", lambda m: f(m["korr_team_summe_b"]))
    row(f"4b. mittlere paarweise Korrelation der Roh-Fehler (>= {MIN_EXP_MINUTES:g} erwartete Min; Paare)", lambda m: f"{f(m['paarkorr'])} ({m['paare']})")
    lines.append(f"  4c. Korrelation Teamfehler Heim und Gast im selben Spiel: {f(res['korr_heim_gast'])} ({res['spiele']} Spiele)")
    return lines


def report(results: dict, infos: dict) -> str:
    lines = ["Konsistenzpruefung Spielerpunkte gegen Teampunkte (analysis/consistency_check.py), nur Zahlen.", "Definitionen und Rechenweg: Kopf der Datei analysis/consistency_check.py.",
             "3. Teamabgleich-Faktor: steht nicht in den Dateien (nur die Ergebnisse A und B); die Haeufigkeit der Grenzen 0,6 und 1,4 ist daraus nicht ermittelbar.",
             "Hinweis: Die Spielerdateien enthalten nur Spieler mit Prognose und Minuten > 0; Spieler, die nicht spielten, fehlen (Abdeckung < 100 %).", ""]
    for name, res in results.items():
        info = infos[name]
        lines.append(f"=== {name} === (Team-Spiele {info['team_spiele']}, erkannte Spiele mit Verlaengerung {info['spiele_ot']}, Spielerzeilen ohne verbundenes Teamspiel {info['spieler_zeilen_ohne_teamspiel']})")
        for grp, r in res.items():
            lines += block_text(f"{name}, {grp}", r)
        lines.append("")
    return "\n".join(lines) + "\n"


def run(pbp_dir: Path, seasons=SEASONS) -> str:
    gs, ps, infos, results = [], [], {}, {}
    for s in seasons:
        players, teams = load_season(pbp_dir, s)
        g, p, info = team_games(players, teams, s)
        gs.append(g); ps.append(p)
        infos[s], results[s] = info, evaluate(g, p)
    if len(seasons) > 1:
        g_all, p_all = pd.concat(gs, ignore_index=True), pd.concat(ps, ignore_index=True)
        g_all["spiel_id"] = g_all["saison"] + "|" + g_all["spiel_id"]                # Spiel-IDs sind je Saison eindeutig; Saison davor, damit nichts vermischt wird
        p_all["spiel_id"] = p_all["saison"] + "|" + p_all["spiel_id"]
        infos["gesamt"] = {k: sum(i[k] for i in infos.values()) for k in ("team_spiele", "spiele_ot", "spieler_zeilen_ohne_teamspiel")}
        results["gesamt"] = evaluate(g_all, p_all)
    return report(results, infos)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--out", default=str(ROOT / "analysis" / "results" / "consistency_check.txt"))
    args = ap.parse_args(argv)
    text = run(Path(args.pbp_dir))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

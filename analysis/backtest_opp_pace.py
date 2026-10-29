"""
Experiment 2.3a: Erklaeren Gegner-Verteidigung (D), Tempo (P) und Heim/Auswaerts (H) den Rest-Fehler der erwarteten Spielerpunkte? NUR ANALYSE, kein Netz; engine/player_forecast.py und alle
bestehenden Dateien bleiben unveraendert. Schreibt analysis/results/opp_pace.txt.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_opp_pace.py

Daten: Prognosen <pbp-dir>/derived/forecast_players_<Saison>.csv.gz (erwartete Punkte/Minuten roh, tatsaechliche Punkte); Gegner, Heim/Auswaerts, Teampunkte und Spielzahl aus den lokalen Spielerzeilen
(data/cache backtest_player_games_2023-24, backtest_player_games_2024-25, player_games_2025-26; Teampunkte = Summe der Spielerpunkte, Verbindung ueber Spieler-ID und Datum wie in analysis/export_forecasts.py).
Je Zeile nur Spiele der Teams VOR dem Spieltag und nur derselben Saison; mindestens 5 Spiele Verlauf (Spielerteam und Gegner), sonst Zeile ausgelassen und gezaehlt.
  D = Mittel der vom Gegner zugelassenen Punkte minus Liga-Schnitt (Punkte je Team und Spiel vor dem Spieltag), mit n / (n + 10) Richtung 0 gezogen (n = Spiele des Gegners).
  P = Tempo-Naeherung: Mittel der Gesamtpunkte (beide Teams) der Spiele des Spielerteams und der Spiele des Gegners, minus Liga-Schnitt der Gesamtpunkte. Ballbesitze stehen lokal NICHT zur Verfuegung
      (die Spielerzeilen haben keine Ballverluste und Rebounds), deshalb Punkte-Naeherung.
  H = 1 Heim, 0 Auswaerts.
Test: e = (tatsaechliche - erwartete Punkte roh) / max(erwartete Punkte roh, 3), nur Zeilen mit erwarteten Minuten roh >= 10; ohne Verlaengerungsspiele (Teamsumme der Minuten > 245; Teamverlauf enthaelt sie) und ohne Spiel 0022400061.
Fit e ~ a + b1 D + b2 P + b3 H (je Faktor allein, alle zusammen, dazu nur a als Kontrolle) aus zwei Saisons, Test auf der dritten (alle drei Kombinationen); Korrektur: erwartete Punkte x (1 + Fit).
Koeffizienten mit 95-%-Intervall (Bootstrap nach Spielen, 1000 Ziehungen).
REGEL (vorab): Ein Faktor zaehlt nur, wenn sein Koeffizient in allen drei Anpassungen dasselbe Vorzeichen hat, der RMSE der Starter in allen drei Testsaisons sinkt und in keiner Gruppe in zwei Saisons
schlechter wird (jeweils gegen R; angewendet auf das Modell mit dem Faktor allein, zusaetzlich wird das gemeinsame Modell gezeigt).
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from analysis import ppm_decomposition as pdc  # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
MIN_GAMES = 5
SHRINK_K = 10.0
MIN_EXP_MINUTES = 10.0
GROUPS = ("Starter", "Bank", "1-9 Spiele", "ab 30 Spiele")
MODELS = {"nur a": [], "D": ["D"], "P": ["P"], "H": ["H"], "D+P+H": ["D", "P", "H"]}
BOOT = 1000
OUT = HERE / "results" / "opp_pace.txt"


# ----------------------------------------------------------------------------- Teamdaten
def team_games(rows: list[dict]) -> dict:
    """{(Saison, Team): [(Datum, Punkte fuer, Punkte gegen)]}, Teampunkte = Summe der Spielerpunkte je Spiel und Team."""
    pts, meta = defaultdict(int), {}
    for r in rows:
        key = (str(r["game_id"]), r["team"])
        pts[key] += int(r["points"])
        meta[key] = (r["season"], pdc.date_int(r["date"]), r["opponent"])
    out = defaultdict(list)
    for (gid, team), p in pts.items():
        season, day, opp = meta[(gid, team)]
        q = pts.get((gid, opp))
        if q is None:
            continue
        out[(season, team)].append((day, p, q))
    return {k: sorted(v) for k, v in out.items()}


class TeamStats:
    """Kumulierte Teamsummen je (Saison, Team) und Liga je Saison; Zugriff 'vor Datum D'."""

    def __init__(self, tg: dict):
        self.dates, self.cum = {}, {}
        league = defaultdict(list)
        for key, lst in tg.items():
            self.dates[key] = np.array([d for d, _, _ in lst])
            self.cum[key] = np.vstack([np.zeros(2), np.cumsum([[p, q] for _, p, q in lst], axis=0)])
            for d, p, _ in lst:
                league[key[0]].append((d, p))
        self.ldates, self.lcum = {}, {}
        for s, lst in league.items():
            by_day = defaultdict(lambda: np.zeros(2))
            for d, p in lst:
                by_day[d] += [p, 1]
            ds = sorted(by_day)
            self.ldates[s] = np.array(ds)
            self.lcum[s] = np.vstack([np.zeros(2), np.cumsum([by_day[d] for d in ds], axis=0)])

    def team(self, season: str, team: str, day: int):
        """(n, Punkte fuer, Punkte gegen) vor day."""
        key = (season, team)
        if key not in self.dates:
            return 0, 0.0, 0.0
        k = int(np.searchsorted(self.dates[key], day, side="left"))
        c = self.cum[key][k]
        return k, float(c[0]), float(c[1])

    def league_mean(self, season: str, day: int) -> float:
        """Punkte je Team und Spiel vor day (nan, wenn keins)."""
        if season not in self.ldates:
            return float("nan")
        k = int(np.searchsorted(self.ldates[season], day, side="left"))
        c = self.lcum[season][k]
        return float(c[0] / c[1]) if c[1] > 0 else float("nan")


def features(ts: TeamStats, season: str, team: str, opp: str, home: bool, day: int):
    """(D, P, H) oder None, wenn Spielerteam oder Gegner weniger als 5 Spiele Verlauf haben."""
    n_t, f_t, a_t = ts.team(season, team, day)
    n_o, f_o, a_o = ts.team(season, opp, day)
    lm = ts.league_mean(season, day)
    if n_t < MIN_GAMES or n_o < MIN_GAMES or not np.isfinite(lm):
        return None
    D = (n_o / (n_o + SHRINK_K)) * (a_o / n_o - lm)
    P = ((f_t + a_t) / n_t + (f_o + a_o) / n_o) / 2.0 - 2.0 * lm
    return D, P, 1.0 if home else 0.0


# ----------------------------------------------------------------------------- Fit
def ols(X: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    A = np.column_stack([np.ones(len(y)), X]) if X.size else np.ones((len(y), 1))
    if w is None:
        return np.linalg.lstsq(A, y, rcond=None)[0]
    sw = np.sqrt(w)
    return np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)[0]


def bootstrap_ci(X: np.ndarray, y: np.ndarray, game_idx: np.ndarray, B: int, rng) -> np.ndarray:
    """95-%-Intervall der Koeffizienten (inkl. a), Ziehung nach Spielen (game_idx: 0..G-1 je Zeile)."""
    G = int(game_idx.max()) + 1
    A = np.column_stack([np.ones(len(y)), X]) if X.size else np.ones((len(y), 1))
    out = []
    for _ in range(B):
        cnt = np.bincount(rng.integers(0, G, G), minlength=G).astype(float)
        w = cnt[game_idx]
        AtW = A.T * w
        try:
            out.append(np.linalg.solve(AtW @ A, AtW @ y))
        except np.linalg.LinAlgError:
            continue
    out = np.array(out)
    return np.percentile(out, [2.5, 97.5], axis=0)


def corrected(epts: np.ndarray, X: np.ndarray, beta: np.ndarray) -> np.ndarray:
    fit = beta[0] + (X @ beta[1:] if X.size else 0.0)
    return epts * (1.0 + fit)


def err_stats(pred: np.ndarray, act: np.ndarray) -> dict:
    e = act - pred
    return {"n": len(e), "rmse": float(np.sqrt((e ** 2).mean())) if len(e) else float("nan"), "bias": float(e.mean()) if len(e) else float("nan")}


def decide_factor(signs_ok: bool, starter_rmse_lower: bool, groups_worse_seasons: dict) -> dict:
    """groups_worse_seasons: {Gruppe: Zahl der Testsaisons mit RMSE schlechter als R}."""
    no_group = all(v < 2 for v in groups_worse_seasons.values())
    return {"Vorzeichen gleich": signs_ok, "Starter-RMSE sinkt in allen Saisons": starter_rmse_lower, "keine Gruppe in 2 Saisons schlechter": no_group,
            "Regel": signs_ok and starter_rmse_lower and no_group}


# ----------------------------------------------------------------------------- Zeilen
def build_rows(pbp: Path, cache: Path) -> dict:
    local = pdc.load_local(cache)
    ts = TeamStats(team_games(local))
    hist = pdc.History(local)
    by_player = {(int(r["person_id"]), pdc.date_int(r["date"])): r for r in local}
    fc = [r for s in SEASONS for r in pdc.load_forecast_rows(pbp, s)]
    kept, skipped, ot_skip, nolocal = [], defaultdict(int), 0, 0
    for r in fc:
        if r["ot"] or r["emin"] < MIN_EXP_MINUTES:
            ot_skip += r["ot"]
            continue
        loc = by_player.get((r["pid"], r["day"]))
        if loc is None:
            nolocal += 1
            continue
        f = features(ts, r["season"], r["team"], loc["opponent"], bool(loc["home"]), r["day"])
        if f is None:
            skipped[r["season"]] += 1
            continue
        a = hist.player(r["pid"], r["day"], "alle")
        kept.append((r, f, int(a[5])))
    n = len(kept)
    X = np.array([f for _, f, _ in kept]); epts = np.array([r["epts"] for r, _, _ in kept]); act = np.array([r["act"] for r, _, _ in kept])
    gid = {}
    game_idx = np.array([gid.setdefault((r["season"], r["game"]), len(gid)) for r, _, _ in kept])
    return {"X": X, "epts": epts, "act": act, "e": (act - epts) / np.maximum(epts, 3.0), "season": np.array([r["season"] for r, _, _ in kept]), "emin": np.array([r["emin"] for r, _, _ in kept]),
            "ngames": np.array([g for _, _, g in kept]), "game_idx": game_idx, "skipped": dict(skipped), "nolocal": nolocal, "n": n}


def group_masks(D: dict) -> dict:
    return {"Starter": D["emin"] > 28.0, "Bank": D["emin"] <= 28.0, "1-9 Spiele": (D["ngames"] >= 1) & (D["ngames"] <= 9), "ab 30 Spiele": D["ngames"] >= 30}


def run(pbp: Path, cache: Path, seed: int = 11, boot: int = BOOT) -> str:
    D = build_rows(pbp, cache)
    gm = group_masks(D)
    rng = np.random.default_rng(seed)
    cols = {"D": 0, "P": 1, "H": 2}
    fits, cis, res = {}, {}, {}
    for test in SEASONS:
        tr = D["season"] != test
        for mname, facs in MODELS.items():
            idx = [cols[f] for f in facs]
            X = D["X"][:, idx] if idx else np.zeros((len(D["e"]), 0))
            beta = ols(X[tr], D["e"][tr])
            fits[(test, mname)] = beta
            gi = np.unique(D["game_idx"][tr], return_inverse=True)[1]
            cis[(test, mname)] = bootstrap_ci(X[tr], D["e"][tr], gi, boot, rng)
            p = corrected(D["epts"], X, beta)
            te = D["season"] == test
            for g in GROUPS:
                m = te & gm[g]
                res[(test, mname, g)] = {"R": err_stats(D["epts"][m], D["act"][m]), "K": err_stats(p[m], D["act"][m])}
    out = ["Experiment 2.3a: Gegner-Verteidigung, Tempo und Heim/Auswaerts gegen den Rest-Fehler der erwarteten Spielerpunkte (beschreibend; Regel unten)", "",
           "WAS DAS MODELL SCHON ENTHAELT (engine/player_forecast.py, gelesen):",
           "  Punkte pro Minute (ppm) kommen nur aus dem eigenen Verlauf des Spielers (zeitgewichtet); Gegner-Verteidigung und Tempo haben KEINEN Einfluss auf die ppm, der Spiel-Total wird mitgefuehrt, aber nicht verwendet.",
           "  Heim/Gast steht nicht als Faktor drin. Der Spread des Spielmodells (er enthaelt den Heimvorteil und die Staerke des Gegners) wirkt nur auf die MINUTEN (Blowout-Abschlag fuer Starter/Rotation),",
           "  die erwarteten Punkte roh haengen darueber indirekt vom Spread ab. Ein Gegner-/Heim-Effekt ueber den Spread ist also in den Minuten schon teilweise enthalten, ein Effekt auf die ppm nicht.",
           "  Ausfaelle von Mitspielern, Ruhetage, Foulprobleme und Overtime sind nicht enthalten.", "",
           f"Zeilen: {D['n']} (erwartete Minuten roh >= {MIN_EXP_MINUTES:.0f}, ohne Verlaengerung und Spiel 0022400061, mind. {MIN_GAMES} Spiele Verlauf von Spielerteam und Gegner in derselben Saison).",
           "Ausgelassen wegen zu wenig Teamverlauf (<5 Spiele): " + ", ".join(f"{s} {D['skipped'].get(s, 0)}" for s in SEASONS) + f". Ohne lokale Zeile: {D['nolocal']}. Tempo: Punkte-Naeherung (Ballbesitze lokal nicht vorhanden).", "",
           "1. KOEFFIZIENTEN DER ANPASSUNGEN (e = Fehler relativ zu den erwarteten Punkten; Koeffizient je 1 Punkt D bzw. P, H = Heim minus Auswaerts; Intervall 95 % Bootstrap nach Spielen)"]
    for mname, facs in MODELS.items():
        for test in SEASONS:
            b, ci = fits[(test, mname)], cis[(test, mname)]
            names = ["a"] + facs
            out.append(f"  Modell {mname}, Anpassung ohne {test}: " + "; ".join(f"{n} = {b[i]:+.4f} [{ci[0][i]:+.4f}, {ci[1][i]:+.4f}]" for i, n in enumerate(names)))
    out += ["", "2. TABELLEN (Punkte: Zeilen / RMSE R -> korrigiert / Verzerrung R -> korrigiert, Verzerrung = tatsaechlich minus erwartet)"]
    for g in GROUPS:
        out.append(f"Gruppe {g}")
        out.append("  " + "Modell".ljust(8) + "".join(f"{s:^52}" for s in SEASONS))
        for mname in MODELS:
            cells = []
            for s in SEASONS:
                r = res[(s, mname, g)]
                cells.append(f"{r['R']['n']:>6d}  {r['R']['rmse']:.3f}->{r['K']['rmse']:.3f}  {r['R']['bias']:+.3f}->{r['K']['bias']:+.3f}")
            out.append("  " + mname.ljust(8) + " | ".join(c.ljust(50) for c in cells))
        out.append("")
    out.append("3. REGEL (je Faktor, Modell mit dem Faktor allein; zusaetzlich das gemeinsame Modell)")
    for fac in ("D", "P", "H"):
        coefs = [fits[(t, fac)][1] for t in SEASONS]
        signs_ok = all(c > 0 for c in coefs) or all(c < 0 for c in coefs)
        rm = [res[(t, fac, "Starter")] for t in SEASONS]
        lower = all(r["K"]["rmse"] < r["R"]["rmse"] for r in rm)
        worse = {g: sum(res[(t, fac, g)]["K"]["rmse"] > res[(t, fac, g)]["R"]["rmse"] for t in SEASONS) for g in GROUPS}
        d = decide_factor(signs_ok, lower, worse)
        out.append(f"  {fac}: Koeffizienten {', '.join(f'{c:+.4f}' for c in coefs)}; Vorzeichen gleich: {'ja' if signs_ok else 'nein'}; Starter-RMSE sinkt in allen drei Saisons: {'ja' if lower else 'nein'}; "
                   f"Gruppen mit RMSE schlechter in Saisons (von 3): " + ", ".join(f"{g} {n}" for g, n in worse.items()) + f"; Regel erfuellt: {'JA' if d['Regel'] else 'NEIN'}")
    for fi, fac in enumerate(("D", "P", "H")):
        coefs = [fits[(t, "D+P+H")][1 + fi] for t in SEASONS]
        out.append(f"  gemeinsames Modell, Koeffizient {fac}: {', '.join(f'{c:+.4f}' for c in coefs)} (Vorzeichen {'gleich' if all(c > 0 for c in coefs) or all(c < 0 for c in coefs) else 'verschieden'})")
    rm = [res[(t, "D+P+H", "Starter")] for t in SEASONS]
    out.append("  gemeinsames Modell, Starter-RMSE R -> korrigiert: " + "; ".join(f"{t} {r['R']['rmse']:.3f}->{r['K']['rmse']:.3f}" for t, r in zip(SEASONS, rm)))
    kon = [res[(t, "nur a", "Starter")] for t in SEASONS]
    out.append("  Kontrolle 'nur a' (nur Verschiebung): Starter-RMSE R -> korrigiert: " + "; ".join(f"{t} {r['R']['rmse']:.3f}->{r['K']['rmse']:.3f}" for t, r in zip(SEASONS, kon)))
    out += ["", "4. NICHT GEPRUEFT", "  Signifikanz der RMSE-Unterschiede (nur Bootstrap-Intervalle der Koeffizienten); Chancen/Meilensteine; Ballbesitze (nicht lokal verfuegbar); Positionen/Gegner-Verteidigung je Position;",
            "  Zusammenspiel mit Teamabgleich und Spread im Minuten-Modell; zeitgewichtete oder saisonuebergreifende Teamwerte; Teamverlauf enthaelt Verlaengerungsspiele; Fit ueber alle Gruppen gemeinsam (nicht je Gruppe)."]
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

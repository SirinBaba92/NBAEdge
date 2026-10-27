"""
Obergrenze fuer den Nutzen von Verletzungen/Ausfaellen im Sieger-Modell, Regular Season 2025-26, walk-forward. NUR LESEND: data/cache (games_2015-2025, player_games_2025-26),
schreibt nur analysis/reports/winner_injuries_2025-26.txt. Das Produktivmodell wird nicht veraendert.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_winner_injuries.py

WICHTIG: Wer in einem Spiel fehlte, ist Wissen aus der Zukunft (im Betrieb waere nur Gemeldetes und Unsicheres bekannt). Alle Ergebnisse sind deshalb eine OBERGRENZE des Nutzens.
Daten: data/cache/player_games_2025-26.json (NBA.com leaguegamelog: Minuten und Punkte je Spieler und Spiel; nur Spieler mit Einsatz oder 0 Minuten haben eine Zeile). Ein Spieler fehlt in einem Spiel,
wenn er keine Zeile hat oder 0 Minuten. Stammspieler = Top 8 des Teams nach den bis dahin (vor dem Spiel) gesammelten Minuten MIT diesem Team (nur Spiele davor). Erst ab dem 10. Teamspiel bewertet.
Wechselt ein Stammspieler das Team (sein naechster Einsatz nach diesem Spiel ist fuer ein anderes Team), zaehlt er dort nicht als fehlend (kein Ausfall, sondern Transfer).
Ausfall-Mass je Team und Spiel (zwei Varianten): PUNKTE = Summe (Punkte pro gespieltem Spiel des fehlenden Stammspielers / Teampunkte pro Teamspiel), jeweils bis dahin;
MINUTEN = Summe (Minuten pro gespieltem Spiel / 240). Ausfall-Differenz D = Mass Heim minus Mass Gast (positiv: Heim fehlt mehr).
Modell: Replay der Produktiv-Engine (analysis/replica_tunable.run), Spread = round(diff / 50, 1), Siegchance = Normalverteilung, Sigma 13,2, 3-97 % (wie die App, ohne Markt-Mischung).
Modellfehler = Ist-Spread (Heim-Punkte minus Gast-Punkte) minus Modell-Spread. Steigung = OLS des Fehlers auf D (mit Achsenabschnitt), Bootstrap nach Spielen, 95 %, 2000 Ziehungen.
Korrektur: Spread' = Spread + Steigung * D (Steigung auf einer Haelfte bestimmt, auf der anderen geprueft, und umgekehrt); Brier/Log-Loss der Siegchance gegen heute, gepaarter Bootstrap.
Haelften: bewertete Spiele in Datumsreihenfolge, erste Haelfte = erste n/2.
"""
import json
import sys
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.stats import norm

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_winner as bw  # noqa: E402
import backtest_winner_calibration as bc  # noqa: E402
from bt_common import CACHE, load_games, logloss  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR, MAX_WIN_PROB, MIN_WIN_PROB  # noqa: E402

OUT = HERE / "reports" / "winner_injuries_2025-26.txt"
SIGMA = 13.2
TOP_N, TOP_STAR, MIN_GAMES = 8, 3, 10
B = 2000


def prob(mu):
    return np.clip(norm.cdf(np.round(mu, 1) / SIGMA), MIN_WIN_PROB, MAX_WIN_PROB)


def ols(x, y):
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    return float(((x - xm) * (y - ym)).sum() / sxx) if sxx > 0 else 0.0


def slope_ci(x, y, seed):
    idx = bc.boot_idx(len(x), seed)
    bs = np.array([ols(x[i], y[i]) for i in idx])
    return ols(x, y), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def paired(d, seed):
    bs = d[bc.boot_idx(len(d), seed)].mean(axis=1)
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def absences():
    """{(game_id, team): {'n_prior': Teamspiele davor, 'miss': [(person_id, rank, ppg_share, min_share)]}} und {game_id: (date, {team,...})}."""
    rows = json.loads((CACHE / "player_games_2025-26.json").read_text())["rows"]
    games = defaultdict(lambda: defaultdict(dict))        # gid -> team -> pid -> row
    gdate = {}
    for r in rows:
        games[r["game_id"]][r["team"]][r["person_id"]] = r
        gdate[r["game_id"]] = r["date"]
    appear = defaultdict(list)                             # pid -> [(date, gid, team)] mit Minuten > 0
    for r in rows:
        if (r["minutes"] or 0) > 0:
            appear[r["person_id"]].append((r["date"], r["game_id"], r["team"]))
    for v in appear.values():
        v.sort()
    cum = defaultdict(lambda: defaultdict(lambda: {"min": 0.0, "pts": 0.0, "gp": 0}))   # team -> pid -> Summen
    team_pts, team_min, team_gp = defaultdict(float), defaultdict(float), defaultdict(int)
    out = {}
    for gid in sorted(games, key=lambda g: (gdate[g], g)):
        for team, prow in games[gid].items():
            res = {"n_prior": team_gp[team], "miss": []}
            if team_gp[team] >= MIN_GAMES:
                top = sorted(cum[team].items(), key=lambda kv: -kv[1]["min"])[:TOP_N]
                for rank, (pid, s) in enumerate(top, 1):
                    row = prow.get(pid)
                    if row is not None and (row["minutes"] or 0) > 0:
                        continue
                    nxt = next((a for a in appear[pid] if (a[0], a[1]) > (gdate[gid], gid)), None)
                    if nxt is not None and nxt[2] != team:
                        continue                           # Transfer, kein Ausfall
                    tppg = team_pts[team] / team_gp[team]
                    res["miss"].append((pid, rank, (s["pts"] / s["gp"]) / tppg, (s["min"] / s["gp"]) / 240.0))
            out[(gid, team)] = res
        for team, prow in games[gid].items():                # Update NACH der Bewertung
            team_gp[team] += 1
            for pid, r in prow.items():
                m = r["minutes"] or 0
                team_pts[team] += r["points"] or 0
                team_min[team] += m
                if m > 0:
                    c = cum[team][pid]
                    c["min"] += m
                    c["pts"] += r["points"] or 0
                    c["gp"] += 1
    return out, games, gdate


def main():
    ab, pgames, gdate = absences()
    gid_by = {}
    for gid, t in pgames.items():
        gid_by[(gdate[gid], frozenset(t))] = gid
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **bw.PRODUCTION)
    sel = np.where(rows["season"] == bw.SEASON)[0]
    sel = sel[rows["post"][sel].astype(int) == 0]
    recs, no_log, too_early = [], 0, 0
    for i in sel:
        g = games[i]
        h, a = g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"]
        gid = gid_by.get((g["date"][:10], frozenset((h, a))))
        if gid is None:
            no_log += 1
            continue
        ah, aa = ab[(gid, h)], ab[(gid, a)]
        if ah["n_prior"] < MIN_GAMES or aa["n_prior"] < MIN_GAMES:
            too_early += 1
            continue
        f = lambda r, k: sum(m[k] for m in r["miss"])
        recs.append((g["date"][:10], gid, float(rows["diff"][i]) / ELO_TO_SPREAD_FACTOR, float(rows["margin"][i]),
                     f(ah, 2) - f(aa, 2), f(ah, 3) - f(aa, 3), sum(1 for m in ah["miss"] if m[1] <= TOP_STAR), sum(1 for m in aa["miss"] if m[1] <= TOP_STAR), len(ah["miss"]), len(aa["miss"])))
    recs.sort(key=lambda r: (r[0], r[1]))
    mu = np.array([r[2] for r in recs])
    spread = np.round(mu, 1)
    margin = np.array([r[3] for r in recs])
    y = (margin > 0).astype(float)
    err = margin - spread
    Dp, Dm = np.array([r[4] for r in recs]), np.array([r[5] for r in recs])
    s3h, s3a = np.array([r[6] for r in recs]), np.array([r[7] for r in recs])
    nmh, nma = np.array([r[8] for r in recs]), np.array([r[9] for r in recs])
    n = len(recs)
    h = (n + 1) // 2
    halves = {"ganze Saison": slice(0, n), "Hälfte 1": slice(0, h), "Hälfte 2": slice(h, n)}
    dts = [r[0] for r in recs]
    L = [f"VERLETZUNGEN IM SIEGER-MODELL: OBERGRENZE DES NUTZENS, REGULAR SEASON 2025-26 — erstellt {datetime.now():%Y-%m-%d %H:%M} (analysis/backtest_winner_injuries.py)",
         "Reine Messung, Produktivmodell unverändert. WISSEN AUS DER ZUKUNFT: wer fehlte, steht erst nach dem Spiel fest; alle Ergebnisse sind eine Obergrenze dessen, was mit echten (vorab gemeldeten, unsicheren) Ausfällen erreichbar wäre.",
         f"Daten: Spielerzeilen aus data/cache/player_games_2025-26.json (nur Einsätze und 0-Minuten-Zeilen; fehlende Zeile = nicht eingesetzt). Regular Season laut BallDontLie: {len(sel)} Spiele; ohne Spielerdaten: {no_log} (Cup-K.-o.-Spiele laufen in der Liga-Datei nicht unter Regular Season);",
         f"in den ersten {MIN_GAMES} Teamspielen nicht bewertet: {too_early}; bewertet: {n} ({dts[0]} bis {dts[-1]}). Hälfte 1: {h} Spiele bis {dts[h - 1]}, Hälfte 2: {n - h} Spiele ab {dts[h]}.",
         f"Stammspieler = Top {TOP_N} nach Minuten bis dahin mit diesem Team. Fehlend = 0 Minuten oder keine Zeile, außer bei Teamwechsel danach. Ausfall-Differenz D = Heim minus Gast (positiv: Heim fehlt mehr, Erwartung: Fehler-Steigung NEGATIV).",
         ""]
    L.append("0. DATENLAGE")
    L.append(f"  Je Spiel und Team liegen die Einsatzminuten und Punkte aller Spieler vor; daraus ergibt sich pro Spiel, welche Top-{TOP_N}-Spieler (nach Minuten bis dahin) nicht eingesetzt wurden. Ob es Verletzung, Schonung oder Sperre war, steht nicht in den Daten.")
    L.append(f"  Spiele mit mindestens einem fehlenden Stammspieler (Top {TOP_N}): Heim {int((nmh > 0).sum())}, Gast {int((nma > 0).sum())}, mindestens ein Team {int(((nmh > 0) | (nma > 0)).sum())} von {n}. Ø fehlende Stammspieler je Team und Spiel: {np.mean(np.r_[nmh, nma]):.2f}.")
    L.append(f"  Streuung (Standardabweichung) der Ausfall-Differenz D: Punkte-Anteil {np.std(Dp):.3f}, Minuten-Anteil {np.std(Dm):.3f}.")
    L.append("")
    L.append("2. MODELLFEHLER (Ist-Spread minus Modell-Spread) GEGEN AUSFALL-DIFFERENZ D")
    L.append(f"  Ø Fehler ganze Saison {err.mean():+.2f} Pkt, Streuung des Fehlers {err.std():.2f} Pkt. Steigung = Punkte Fehler je 1,0 Ausfall-Anteil (ein Stammspieler mit 20 % Teampunkten = 0,20).")
    L.append(f"  {'Maß':<10}{'Zeitraum':<14}{'n':>6}{'Steigung [95 %]':>26}{'Achsenabschnitt':>17}{'R²':>8}")
    slopes = {}
    for mi, (mn, D) in enumerate((("Punkte", Dp), ("Minuten", Dm))):
        for hi, (hn, sl) in enumerate(halves.items()):
            s, lo, hi_ = slope_ci(D[sl], err[sl], 10 + mi * 10 + hi)
            a0 = err[sl].mean() - s * D[sl].mean()
            r2 = np.corrcoef(D[sl], err[sl])[0, 1] ** 2
            slopes[(mn, hn)] = (s, lo, hi_)
            L.append(f"  {mn:<10}{hn:<14}{len(D[sl]):>6}{f'{s:+.2f} [{lo:+.2f}; {hi_:+.2f}]':>26}{a0:>+17.2f}{r2:>8.3f}")
    L.append("")
    L.append("3. EINFACHE KORREKTUR: Spread' = Spread + Steigung * D; Steigung auf der einen Hälfte bestimmt, auf der anderen geprüft (und umgekehrt)")
    L.append("   Differenz Korrektur minus heute (negativ = besser), gepaarter Bootstrap; x10^-3.")
    L.append(f"  {'Maß':<10}{'Bestimmt auf → geprüft auf':<30}{'Steigung':>10}{'Brier heute':>13}{'Brier korr.':>13}{'ΔBrier [95 %]':>26}{'ΔLog-Loss [95 %]':>28}")
    for mi, (mn, D) in enumerate((("Punkte", Dp), ("Minuten", Dm))):
        for k, (a_, b_) in enumerate((("Hälfte 1", "Hälfte 2"), ("Hälfte 2", "Hälfte 1"))):
            sA, sB = halves[a_], halves[b_]
            beta = ols(D[sA], err[sA])
            p0 = prob(mu[sB])
            p1 = prob(mu[sB] + beta * D[sB])
            yb = y[sB]
            db = (p1 - yb) ** 2 - (p0 - yb) ** 2
            dl = logloss(p1, yb) - logloss(p0, yb)
            mb, lb, hb = paired(db, 100 + mi * 10 + k)
            ml, ll_, hl = paired(dl, 200 + mi * 10 + k)
            L.append(f"  {mn:<10}{a_ + ' → ' + b_:<30}{beta:>+10.2f}{((p0 - yb) ** 2).mean():>13.4f}{((p1 - yb) ** 2).mean():>13.4f}{f'{mb * 1000:+.2f} [{lb * 1000:+.2f}; {hb * 1000:+.2f}]':>26}{f'{ml * 1000:+.2f} [{ll_ * 1000:+.2f}; {hl * 1000:+.2f}]':>28}")
    L.append("  Zum Vergleich ohne Trennung (Steigung auf der GANZEN Saison bestimmt und dort bewertet, also im Prüfdatensatz mit angepasst; nur Größenordnung der Obergrenze):")
    for mn, D in (("Punkte", Dp), ("Minuten", Dm)):
        beta = ols(D, err)
        db = (prob(mu + beta * D) - y) ** 2 - (prob(mu) - y) ** 2
        m_, l_, h_ = paired(db, 300)
        L.append(f"   {mn:<10}Steigung {beta:+.2f}: ΔBrier {m_ * 1000:+.2f} x10^-3 [{l_ * 1000:+.2f}; {h_ * 1000:+.2f}]")
    L.append("")
    L.append(f"4. ZUSATZ: SPIELE MIT MINDESTENS EINEM FEHLENDEN TOP-{TOP_STAR}-SPIELER")
    anyst = (s3h > 0) | (s3a > 0)
    L.append(f"  Spiele mit mindestens einem fehlenden Top-{TOP_STAR}-Spieler: {int(anyst.sum())} von {n} ({100 * anyst.mean():.1f} %); Heim fehlt (Top-{TOP_STAR}): {int((s3h > 0).sum())}, Gast fehlt: {int((s3a > 0).sum())}, beide: {int(((s3h > 0) & (s3a > 0)).sum())}.")
    only_h, only_a = (s3h > 0) & (s3a == 0), (s3a > 0) & (s3h == 0)
    own = np.r_[err[only_h], -err[only_a]]            # Fehler aus Sicht des betroffenen Teams (Ist-Marge minus Modell-Marge des Teams)
    ref = err[~anyst]
    def msd(v, seed):
        m, lo, hi = bc_mean(v, seed)
        return f"{m:+.2f} [{lo:+.2f}; {hi:+.2f}]"
    L.append(f"  Fehler aus Sicht des betroffenen Teams (Ist-Marge minus Modell-Marge des Teams; nur Spiele, in denen genau eine Seite einen Top-{TOP_STAR}-Spieler vermisst, n {len(own)}): Ø {msd(own, 1)} Pkt (negativ = Team schlechter als das Modell erwartet).")
    L.append(f"  Spiele ohne fehlenden Top-{TOP_STAR}-Spieler (n {int((~anyst).sum())}): Ø Fehler aus Sicht Heim {msd(ref, 2)} Pkt (Vergleichswert, Heimseite).")
    L.append(f"  Betrag des Fehlers (MAE): mit fehlendem Top-{TOP_STAR}-Spieler {np.abs(err[anyst]).mean():.2f} Pkt (n {int(anyst.sum())}), ohne {np.abs(err[~anyst]).mean():.2f} Pkt (n {int((~anyst).sum())}).")
    for tag, mk in (("Hälfte 1", halves["Hälfte 1"]), ("Hälfte 2", halves["Hälfte 2"])):
        a_ = anyst[mk]; e_ = err[mk]; oh, oa = only_h[mk], only_a[mk]
        v = np.r_[e_[oh], -e_[oa]]
        L.append(f"  {tag}: {int(a_.sum())} Spiele mit fehlendem Top-{TOP_STAR}; Fehler aus Sicht des betroffenen Teams {msd(v, 5)} Pkt (n {len(v)}); MAE mit {np.abs(e_[a_]).mean():.2f}, ohne {np.abs(e_[~a_]).mean():.2f}.")
    L += ["", "Hinweis: Obergrenze, keine Empfehlung. Ob ein Ausfall vorab bekannt gewesen wäre, ist hier nicht berücksichtigt; ebenso wenig, dass der Markt Ausfälle teils schon einpreist (die App mischt den Markt zum Spread mit 25 %)."]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def bc_mean(v, seed):
    v = np.asarray(v, float)
    bs = v[bc.boot_idx(len(v), seed)].mean(axis=1)
    return float(v.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


if __name__ == "__main__":
    main()

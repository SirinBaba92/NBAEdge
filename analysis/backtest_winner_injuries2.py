"""
Verfeinerte Verletzungs-Messung fuer das Sieger-Modell, Regular Season 2025-26, walk-forward. NUR LESEND: data/cache, schreibt nur analysis/reports/winner_injuries2_2025-26.txt.
Das Produktivmodell wird nicht veraendert. Baut auf analysis/backtest_winner_injuries.py auf (gleiche Daten, gleiches Modell-Replay, gleiche Hilfsfunktionen, gleiche Stichprobe:
Spiele ab dem 10. Teamspiel beider Teams). Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_winner_injuries2.py

WICHTIG: Wer in einem Spiel fehlte, ist Wissen aus der Zukunft. Alle Ergebnisse sind eine OBERGRENZE (im Betrieb waeren nur gemeldete, unsichere Ausfaelle bekannt).
Neues Ausfall-Mass: Stammspieler = Top 8 des Teams nach Minuten in den LETZTEN 10 Teamspielen vor dem Spiel (statt Saison bis dahin); Gewicht = Punkte-Anteil des Spielers an den Teampunkten
dieser 10 Spiele. Ein Spieler fehlt, wenn er keine Zeile oder 0 Minuten hat (Teamwechsel danach: kein Ausfall). Mass je Team = Summe der Gewichte der Fehlenden; D = Heim minus Gast.
Gruppen: "neu fehlt" = hat im vorigen Teamspiel (laut Spielerdatei) gespielt; "laenger fehlt" = fehlte schon im vorigen Teamspiel. D_neu, D_lang, D_alle (= D_neu + D_lang).
Modellfehler = Ist-Spread minus Modell-Spread (Spread = round(diff / 50, 1)); Steigung = OLS mit Achsenabschnitt (je Gruppe einzeln und gemeinsam), Bootstrap nach Spielen, 95 %, 2000 Ziehungen.
Korrektur: Spread' = Spread + faktor * Steigung * D, Steigung auf einer Haelfte bestimmt und auf der anderen geprueft (und umgekehrt); faktor 1 und 0,5 (Zusatz: halbierte Steigung
als Annaeherung an unsichere Meldungen). Brier / Log-Loss der Siegchance (Sigma 13,2, 3-97 %) gegen heute, gepaarter Bootstrap; "gepoolt" = beide Pruefhaelften zusammen (jedes Spiel mit der Steigung der anderen Haelfte).
"""
import sys
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_winner as bw  # noqa: E402
import backtest_winner_calibration as bc  # noqa: E402
import backtest_winner_injuries as bi  # noqa: E402
from bt_common import load_games, logloss  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR  # noqa: E402

OUT = HERE / "reports" / "winner_injuries2_2025-26.txt"
WINDOW, TOP_N, MIN_GAMES = 10, 8, 10


def recent_absences():
    """{(game_id, team): {'n_prior', 'new': Gewicht, 'long': Gewicht, 'n_new', 'n_long'}} (Fenster: letzte 10 Teamspiele)."""
    import json
    rows = json.loads((bi.CACHE / "player_games_2025-26.json").read_text())["rows"]
    games = defaultdict(lambda: defaultdict(dict))
    gdate = {}
    appear = defaultdict(list)
    for r in rows:
        games[r["game_id"]][r["team"]][r["person_id"]] = r
        gdate[r["game_id"]] = r["date"]
        if (r["minutes"] or 0) > 0:
            appear[r["person_id"]].append((r["date"], r["game_id"], r["team"]))
    for v in appear.values():
        v.sort()
    hist = defaultdict(list)                                # team -> [{pid: (min, pts)}, ...] chronologisch
    out = {}
    for gid in sorted(games, key=lambda g: (gdate[g], g)):
        for team, prow in games[gid].items():
            res = {"n_prior": len(hist[team]), "new": 0.0, "long": 0.0, "n_new": 0, "n_long": 0}
            if len(hist[team]) >= MIN_GAMES:
                win = hist[team][-WINDOW:]
                mins, pts = defaultdict(float), defaultdict(float)
                for gm in win:
                    for pid, (m, p) in gm.items():
                        mins[pid] += m
                        pts[pid] += p
                tp = sum(pts.values())
                prev = hist[team][-1]
                for pid in sorted(mins, key=lambda q: -mins[q])[:TOP_N]:
                    row = prow.get(pid)
                    if row is not None and (row["minutes"] or 0) > 0:
                        continue
                    nxt = next((a for a in appear[pid] if (a[0], a[1]) > (gdate[gid], gid)), None)
                    if nxt is not None and nxt[2] != team:
                        continue
                    w = pts[pid] / tp if tp > 0 else 0.0
                    if prev.get(pid, (0.0, 0))[0] > 0:
                        res["new"] += w
                        res["n_new"] += 1
                    else:
                        res["long"] += w
                        res["n_long"] += 1
            out[(gid, team)] = res
        for team, prow in games[gid].items():
            hist[team].append({pid: (float(r["minutes"] or 0), float(r["points"] or 0)) for pid, r in prow.items()})
    return out, games, gdate


def multi_ols(X, y):
    A = np.column_stack([np.ones(len(y)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0][1:]


def multi_ci(X, y, seed):
    idx = bc.boot_idx(len(y), seed)
    bs = np.array([multi_ols(X[i], y[i]) for i in idx])
    b = multi_ols(X, y)
    return [(float(b[k]), float(np.percentile(bs[:, k], 2.5)), float(np.percentile(bs[:, k], 97.5))) for k in range(X.shape[1])]


def main():
    ab, pgames, gdate = recent_absences()
    old_ab, _, _ = bi.absences()
    gid_by = {(gdate[g], frozenset(t)): g for g, t in pgames.items()}
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **bw.PRODUCTION)
    sel = np.where(rows["season"] == bw.SEASON)[0]
    sel = sel[rows["post"][sel].astype(int) == 0]
    recs, no_log, early = [], 0, 0
    for i in sel:
        g = games[i]
        h, a = g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"]
        gid = gid_by.get((g["date"][:10], frozenset((h, a))))
        if gid is None:
            no_log += 1
            continue
        ah, aa = ab[(gid, h)], ab[(gid, a)]
        if ah["n_prior"] < MIN_GAMES or aa["n_prior"] < MIN_GAMES:
            early += 1
            continue
        oh, oa = old_ab[(gid, h)], old_ab[(gid, a)]
        d_old = sum(m[2] for m in oh["miss"]) - sum(m[2] for m in oa["miss"])
        recs.append((g["date"][:10], gid, float(rows["diff"][i]) / ELO_TO_SPREAD_FACTOR, float(rows["margin"][i]), ah["new"] - aa["new"], ah["long"] - aa["long"], d_old,
                     ah["n_new"] + aa["n_new"], ah["n_long"] + aa["n_long"], ah["n_new"], aa["n_new"]))
    recs.sort(key=lambda r: (r[0], r[1]))
    mu = np.array([r[2] for r in recs])
    spread = np.round(mu, 1)
    margin = np.array([r[3] for r in recs])
    y = (margin > 0).astype(float)
    err = margin - spread
    Dn, Dl, Do = (np.array([r[k] for r in recs]) for k in (4, 5, 6))
    Da = Dn + Dl
    n = len(recs)
    h = (n + 1) // 2
    halves = {"ganze Saison": slice(0, n), "Hälfte 1": slice(0, h), "Hälfte 2": slice(h, n)}
    dts = [r[0] for r in recs]
    nn, nl = sum(r[7] for r in recs), sum(r[8] for r in recs)
    L = [f"VERFEINERTE VERLETZUNGS-MESSUNG, SIEGER-MODELL, REGULAR SEASON 2025-26 — erstellt {datetime.now():%Y-%m-%d %H:%M} (analysis/backtest_winner_injuries2.py)",
         "Reine Messung, Produktivmodell unverändert. WISSEN AUS DER ZUKUNFT: wer fehlte, steht erst nach dem Spiel fest; alle Ergebnisse sind eine Obergrenze.",
         f"Stichprobe wie im Vorbericht: {n} Spiele ({dts[0]} bis {dts[-1]}; ohne Spielerdaten {no_log} Cup-K.-o.-Spiele, in den ersten {MIN_GAMES} Teamspielen {early}). Hälfte 1: {h} Spiele bis {dts[h - 1]}, Hälfte 2: {n - h} Spiele ab {dts[h]}.",
         f"Neues Maß: Top {TOP_N} nach Minuten der letzten {WINDOW} Teamspiele, Gewicht = Punkte-Anteil in diesen {WINDOW} Spielen. 'neu fehlt' = spielte im vorigen Teamspiel noch, 'länger fehlt' = fehlte schon im vorigen Teamspiel.",
         f"Fehlende Stammspieler-Einsätze insgesamt: {nn} 'neu fehlt', {nl} 'länger fehlt' (Team-Spiele); Streuung von D: neu {np.std(Dn):.3f}, länger {np.std(Dl):.3f}, alle {np.std(Da):.3f}, altes Maß {np.std(Do):.3f}.",
         f"Spiele mit mindestens einem 'neu fehlt': {sum(1 for r in recs if r[7] > 0)} von {n}; mit mindestens einem 'länger fehlt': {sum(1 for r in recs if r[8] > 0)}. Ø Fehler des Modells {err.mean():+.2f} Pkt, Streuung {err.std():.2f} Pkt.", ""]
    L.append("1+2. STEIGUNG DES MODELLFEHLERS (Punkte je 1,0 Ausfall-Anteil; Erwartung negativ)")
    L.append(f"  {'Maß / Gruppe':<40}{'Zeitraum':<14}{'Steigung [95 %]':>26}{'R²':>8}")
    for mi, (nm, D) in enumerate((("altes Maß (Saison bis dahin, Referenz)", Do), ("neues Maß, alle Fehlenden", Da), ("neu fehlt (einzeln)", Dn), ("länger fehlt (einzeln)", Dl))):
        for hi, (hn, sl) in enumerate(halves.items()):
            s, lo, hi_ = bi.slope_ci(D[sl], err[sl], 10 + mi * 10 + hi)
            L.append(f"  {nm:<40}{hn:<14}{f'{s:+.2f} [{lo:+.2f}; {hi_:+.2f}]':>26}{np.corrcoef(D[sl], err[sl])[0, 1] ** 2:>8.3f}")
        L.append("")
    L.append("  Gemeinsame Regression Fehler ~ D_neu + D_lang (beide Gruppen zugleich):")
    for hi, (hn, sl) in enumerate(halves.items()):
        c = multi_ci(np.column_stack([Dn[sl], Dl[sl]]), err[sl], 60 + hi)
        L.append(f"   {hn:<14} neu fehlt {c[0][0]:+.2f} [{c[0][1]:+.2f}; {c[0][2]:+.2f}]    länger fehlt {c[1][0]:+.2f} [{c[1][1]:+.2f}; {c[1][2]:+.2f}]")
    L += ["", "3+4. KORREKTUR-TEST (Steigung auf einer Hälfte bestimmt, auf der anderen geprüft, und umgekehrt); Spread' = Spread + faktor * Steigung * D",
          "   Differenz Korrektur minus heute (negativ = besser), gepaarter Bootstrap, x10^-3. faktor 0,5 = halbierte Steigung (Annäherung an unsichere Meldungen).",
          f"  {'Maß':<26}{'Faktor':>7}{'Bestimmt → geprüft':>22}{'Steigung':>10}{'Brier heute':>12}{'Brier korr.':>12}{'ΔBrier [95 %]':>24}{'ΔLog-Loss [95 %]':>26}"]
    summary = []
    for mi, (nm, D) in enumerate((("neues Maß, alle Fehlenden", Da), ("nur 'neu fehlt'", Dn), ("altes Maß (Referenz)", Do))):
        for fi, fac in enumerate((1.0, 0.5)):
            p_pool, p0_pool, y_pool = [], [], []
            for k, (a_, b_) in enumerate((("Hälfte 1", "Hälfte 2"), ("Hälfte 2", "Hälfte 1"))):
                sA, sB = halves[a_], halves[b_]
                beta = bi.ols(D[sA], err[sA])
                p0 = bi.prob(mu[sB])
                p1 = bi.prob(mu[sB] + fac * beta * D[sB])
                yb = y[sB]
                mb, lb, hb = bi.paired((p1 - yb) ** 2 - (p0 - yb) ** 2, 100 + mi * 40 + fi * 10 + k)
                ml, ll_, hl = bi.paired(logloss(p1, yb) - logloss(p0, yb), 300 + mi * 40 + fi * 10 + k)
                L.append(f"  {nm:<26}{fac:>7.1f}{a_ + ' → ' + b_:>22}{beta:>+10.2f}{((p0 - yb) ** 2).mean():>12.4f}{((p1 - yb) ** 2).mean():>12.4f}{f'{mb * 1000:+.2f} [{lb * 1000:+.2f}; {hb * 1000:+.2f}]':>24}{f'{ml * 1000:+.2f} [{ll_ * 1000:+.2f}; {hl * 1000:+.2f}]':>26}")
                p_pool.append(p1); p0_pool.append(p0); y_pool.append(yb)
            p1, p0, yb = np.concatenate(p_pool), np.concatenate(p0_pool), np.concatenate(y_pool)
            mb, lb, hb = bi.paired((p1 - yb) ** 2 - (p0 - yb) ** 2, 500 + mi * 10 + fi)
            ml, ll_, hl = bi.paired(logloss(p1, yb) - logloss(p0, yb), 600 + mi * 10 + fi)
            summary.append((nm, fac, (mb, lb, hb), (ml, ll_, hl)))
        L.append("")
    L.append("  GEPOOLT (beide Prüfhälften zusammen, jedes Spiel mit der Steigung der jeweils anderen Hälfte):")
    L.append(f"  {'Maß':<26}{'Faktor':>7}{'ΔBrier x10^-3 [95 %]':>28}{'ΔLog-Loss x10^-3 [95 %]':>30}")
    for nm, fac, b, l in summary:
        L.append(f"  {nm:<26}{fac:>7.1f}{f'{b[0] * 1000:+.2f} [{b[1] * 1000:+.2f}; {b[2] * 1000:+.2f}]':>28}{f'{l[0] * 1000:+.2f} [{l[1] * 1000:+.2f}; {l[2] * 1000:+.2f}]':>30}")
    L += ["", "Hinweis: Obergrenze, keine Empfehlung. Die Gruppen sind nach dem Spiel bekannt; 'neu fehlt' wäre im Betrieb am ehesten vorab zu erfahren, aber unsicher und oft schon im Marktpreis."]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

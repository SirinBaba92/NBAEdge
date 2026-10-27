"""
K-Wert und MoV-Formel des Sieger-Modells, Regular Season 2025-26, walk-forward. NUR LESEND: data/cache, schreibt nur analysis/reports/winner_k_mov_2025-26.txt.
Das Produktivmodell (models/elo.py, config/, data/elo_model.pkl) wird nicht veraendert; die Varianten laufen nur im Nachbau analysis/replica_tunable.py.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_winner_k_mov.py

Varianten: K = 10, 15, 20 (heute), 30 jeweils mit MoV 'heute' (K * 2,2 * ln(Marge + 1)) und '538' (K * (Marge + 3)^0,8 / (7,5 + 0,006 * Rating-Vorsprung des Siegers)).
Alles andere wie heute (Heimvorteil 100, keine Sommer-Regression, Form/Ruhetage). Vor jedem Spiel nur Wissen davor; Siegchance wie die App (Normalverteilung um diff / 50,
auf 1 Nachkommastelle gerundet, Sigma 13,2, 3-97 %), reines Modell ohne Markt-Mischung, nur echte Ergebnisse.
Kennzahlen je Variante fuer ganze Saison / Haelfte 1 / Haelfte 2 (nach Anzahl in Datumsreihenfolge): Brier, Log-Loss, Rekalibrierungs-Steigung (logit P(Heim) = a + b logit p) mit 95 %-Intervall
(Bootstrap nach Spielen, 2000 Ziehungen) und Favorit minus Modell in PP.
Auswahlregel: auf einer Haelfte einstellen, auf der anderen pruefen, und umgekehrt. Eingestellt wird (a) SKALA FEST wie produktiv: nur die Variante (kleinster Brier unter allen 8 inkl. heute);
(b) SKALA NEU: zusaetzlich wird Sigma je Variante auf der Einstell-Haelfte nach Brier neu bestimmt (die Rating-Breite aendert sich mit K/MoV, der feste Faktor 50 passt dann nicht mehr).
Geprueft wird auf der anderen Haelfte gegen HEUTE (K 20, MoV heute, Sigma 13,2; bei (b) zusaetzlich gegen heute mit auf der Einstell-Haelfte neu bestimmtem Sigma): Brier-Differenz (negativ = besser)
mit gepaartem Bootstrap. Eine Variante zaehlt nur, wenn sie auf BEIDEN Pruefhaelften besser als heute ist (Brier-Differenz < 0); als belegt gilt sie nur, wenn zusaetzlich das Intervall beider Haelften unter 0 liegt.
"""
import sys
import warnings
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
from bt_common import load_games, logloss  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR, MAX_WIN_PROB, MIN_WIN_PROB  # noqa: E402

OUT = HERE / "reports" / "winner_k_mov_2025-26.txt"
KS = [10, 15, 20, 30]
MOVS = [("cur", "heute"), ("538", "538")]
HEUTE = ("heute", 20)
SIGMA0 = 13.2
SIG_GRID = [round(6.0 + 0.1 * i, 1) for i in range(0, 281)]        # 6,0 ... 34,0


def name(mov, k):
    return f"MoV {dict(MOVS)[mov]}, K {k}"


def prob(mu, s):
    return np.clip(norm.cdf(np.round(mu, 1) / s), MIN_WIN_PROB, MAX_WIN_PROB)


def best_sigma(mu, y):
    sc = [float(((prob(mu, s) - y) ** 2).mean()) for s in SIG_GRID]
    return SIG_GRID[int(np.argmin(sc))]


def paired(d, seed):
    bs = d[bc.boot_idx(len(d), seed)].mean(axis=1)
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def main():
    games = load_games(2015, 2025)
    data = {}
    for mov, _ in MOVS:
        for k in KS:
            rows, _, _, _ = rt.run(games, K=float(k), hca=100.0, mov=mov, total_alpha=0.1)
            sel = np.where(rows["season"] == bw.SEASON)[0]
            sel = sel[rows["post"][sel].astype(int) == 0]
            order = sorted(range(len(sel)), key=lambda q: (games[sel[q]]["date"][:10], games[sel[q]]["id"]))
            sel = sel[order]
            data[(mov, k)] = (rows["diff"][sel] / ELO_TO_SPREAD_FACTOR, (rows["margin"][sel] > 0).astype(float))
    ys = [v[1] for v in data.values()]
    assert all(np.array_equal(ys[0], y) for y in ys), "Ergebnisse je Variante muessen gleich sein"
    y = ys[0]
    n = len(y)
    h = (n + 1) // 2
    segs = {"ganze Saison": slice(0, n), "Hälfte 1": slice(0, h), "Hälfte 2": slice(h, n)}
    H = ("cur", 20)
    variants = [(m, k) for m, _ in MOVS for k in KS]
    L = [f"K-WERT UND MOV-FORMEL DES SIEGER-MODELLS, REGULAR SEASON 2025-26 — erstellt {datetime.now():%Y-%m-%d %H:%M} (analysis/backtest_winner_k_mov.py)",
         "Reine Messung; am Produktivmodell wird nichts geändert (Varianten laufen nur im Nachbau analysis/replica_tunable.py). Reines Modell ohne Markt-Mischung, nur echte Ergebnisse, nur Wissen vor dem Spiel.",
         f"Spiele: {n}; Hälfte 1 = erste {h}, Hälfte 2 = letzte {n - h} (Datumsreihenfolge). Sieger-Wahrscheinlichkeit wie die App: Normalverteilung um diff/50 (1 Nachkommastelle), Sigma 13,2, 3-97 %.",
         "MoV 'heute' = K * 2,2 * ln(Marge + 1); MoV '538' = K * (Marge + 3)^0,8 / (7,5 + 0,006 * Rating-Vorsprung des Siegers). Heimvorteil 100, keine Sommer-Regression, wie heute. 'heute' = MoV heute, K 20.",
         ""]
    chk = float(((prob(data[H][0], SIGMA0) - y) ** 2).mean())
    L.append(f"Kontrolle: Variante heute ergibt Brier {chk:.4f} (Bericht winner_2025-26.txt: 0,2102).")
    L.append("")
    L.append("1+2. KENNZAHLEN JE VARIANTE (Sigma 13,2 fest). Steigung b > 1: Modell zu vorsichtig; Favorit-Diff = Trefferquote des Favoriten minus Ø Modell-Chance (PP).")
    stats = {}
    for si, (sn, sl) in enumerate(segs.items()):
        L += ["", f"  [{sn}]  (n {len(y[sl])})", f"  {'Variante':<18}{'Brier':>8}{'Log-Loss':>10}{'Steigung b [95 %]':>22}{'Fav − Modell PP':>17}{'Brier − heute (x10^-3)':>25}"]
        for vi, v in enumerate(variants):
            p = prob(data[v][0][sl], SIGMA0)
            yy = y[sl]
            r = bc.recal(p, yy, 100 + si * 20 + vi)
            o = bc.overall(p, yy)
            stats[(sn, v)] = (o["brier"], o["ll"], r["b"], r["b_ci"], o["d"])
            dh = (p - yy) ** 2 - (prob(data[H][0][sl], SIGMA0) - yy) ** 2
            btxt = "%.2f [%.2f; %.2f]" % (r["b"], r["b_ci"][0], r["b_ci"][1])
            L.append(f"  {name(*v):<18}{o['brier']:>8.4f}{o['ll']:>10.4f}{btxt:>22}{100 * o['d']:>+17.1f}{(dh.mean() * 1000 if v != H else 0.0):>25.2f}{'   <- heute' if v == H else ''}")
    L += ["", "3. AUSWAHL NACH DER REGEL (einstellen auf der einen Hälfte, prüfen auf der anderen, und umgekehrt)"]
    verdict = {}
    for mode in ("fest", "neu"):
        L.append("")
        L.append("  (a) SKALA FEST: Sigma 13,2 für alle Varianten; eingestellt wird nur die Variante." if mode == "fest" else
                 "  (b) SKALA NEU: Sigma wird je Variante auf der Einstell-Hälfte nach Brier bestimmt (Raster 6,0-34,0 in 0,1); Vergleich gegen heute fest (13,2) UND gegen heute mit neu bestimmtem Sigma.")
        res = {}
        for tag, (tune, test) in (("Hälfte 1 → Hälfte 2", ("Hälfte 1", "Hälfte 2")), ("Hälfte 2 → Hälfte 1", ("Hälfte 2", "Hälfte 1"))):
            ts, es = segs[tune], segs[test]
            sig = {v: (best_sigma(data[v][0][ts], y[ts]) if mode == "neu" else SIGMA0) for v in variants}
            score = {v: float(((prob(data[v][0][ts], sig[v]) - y[ts]) ** 2).mean()) for v in variants}
            pick = min(score, key=score.get)
            L.append(f"   {tag}: Einstellen auf {tune} (n {len(y[ts])}): bester Brier {score[pick]:.4f} mit {name(*pick)}" + (f", Sigma {sig[pick]:.1f}" if mode == 'neu' else "") + f" (heute: {score[H]:.4f}" + (f", Sigma {sig[H]:.1f}" if mode == 'neu' else "") + ")")
            for v in variants:
                if v == H and mode == "fest":
                    continue
                pv = prob(data[v][0][es], sig[v])
                refs = [("heute fest", prob(data[H][0][es], SIGMA0))] + ([("heute neu", prob(data[H][0][es], sig[H]))] if mode == "neu" else [])
                for rn, pr_ in refs:
                    d = (pv - y[es]) ** 2 - (pr_ - y[es]) ** 2
                    res[(tag, v, rn)] = paired(d, 300 + len(res))
            sel_refs = [("heute fest")] + (["heute neu"] if mode == "neu" else [])
            for rn in sel_refs:
                m, lo, hi = res.get((tag, pick, rn), (0.0, 0.0, 0.0))
                L.append(f"      gewählte Variante {name(*pick)} auf {test} gegen {rn}: Brier-Differenz {m * 1000:+.2f} x10^-3 [{lo * 1000:+.2f}; {hi * 1000:+.2f}]" + ("  (= heute selbst gewählt, kein Unterschied)" if pick == H and rn == 'heute fest' else ""))
        L += ["", f"   Alle Varianten gegen heute auf den Prüfhälften ({'Sigma fest' if mode == 'fest' else 'Sigma je Einstell-Hälfte neu'}); Brier-Differenz x10^-3 [95 %], negativ = besser:"]
        refs = ["heute fest"] + (["heute neu"] if mode == "neu" else [])
        for rn in refs:
            L.append(f"   Referenz {rn}:")
            L.append(f"   {'Variante':<18}{'Prüf. H2 (eingestellt auf H1)':>34}{'Prüf. H1 (eingestellt auf H2)':>34}   Ergebnis")
            for v in variants:
                if v == H and mode == "fest":
                    continue
                a, b = res[("Hälfte 1 → Hälfte 2", v, rn)], res[("Hälfte 2 → Hälfte 1", v, rn)]
                fmt = lambda t: f"{t[0] * 1000:+.2f} [{t[1] * 1000:+.2f}; {t[2] * 1000:+.2f}]"
                both = a[0] < 0 and b[0] < 0
                firm = a[2] < 0 and b[2] < 0
                L.append(f"   {name(*v):<18}{fmt(a):>34}{fmt(b):>34}   " + ("BELEGT (beide Hälften, Intervalle unter 0)" if firm else "besser auf beiden Hälften, aber Intervall schließt 0 ein" if both else "zählt nicht (auf mindestens einer Hälfte nicht besser)"))
                verdict[(mode, rn, v)] = "belegt" if firm else "beide besser" if both else "nein"
    cnt = lambda lab: sum(1 for x in verdict.values() if x == lab)
    L += ["", "FAZIT (nur Beschreibung)",
          f"  Varianten, die auf beiden Prüfhälften besser sind als heute: Skala fest {sum(1 for k, x in verdict.items() if k[0] == 'fest' and x != 'nein')} von 7; Skala neu gegen 'heute fest' {sum(1 for k, x in verdict.items() if k[0] == 'neu' and k[1] == 'heute fest' and x != 'nein')} von 8, gegen 'heute neu' {sum(1 for k, x in verdict.items() if k[0] == 'neu' and k[1] == 'heute neu' and x != 'nein')} von 7.",
          f"  Davon mit Intervallen beider Hälften unter 0 (belegt): {cnt('belegt')}.",
          "  Hinweis: 8 Varianten werden gegen heute getestet (Mehrfachvergleich), Zeilen sind bei 618 Spielen je Hälfte nur grob; kein einzelnes Ergebnis ist eine Empfehlung. Das Produktivmodell bleibt unverändert."]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

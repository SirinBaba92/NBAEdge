"""
Ruhetage, Reise, Hoehenlage im Sieger-Modell (Spread, Siegchance). NUR LESEND: data/cache, schreibt nur analysis/reports/winner_rest_travel.txt.
Keine API-Calls, am Produktivmodell wird nichts geaendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_winner_rest_travel.py

Daten: data/cache/games_2015..2025.json (BallDontLie; Datum, Heim/Gast, Punkte, ist_stage). Replay des heutigen Modells ueber analysis/replica_tunable.run
(K 20, Heimvorteil 100, MoV heute): Modell-Spread mu = Elo-Differenz / 50 (Heim-Sicht, positiv = Heim staerker), reines Modell ohne Markt.
Fehler je Spiel = Ist-Spread (Heimpunkte minus Gastpunkte) minus mu; nur Regular Season (ohne Playoffs; Cup-Halbfinale/Finale in Las Vegas ausgeschlossen).
Siegchance wie heute: Normalverteilung um den auf 0,1 gerundeten Spread, Sigma 13,2, Clip 3-97 %.

Faktoren (nur Wissen vor Anpfiff; Spielplan und Ergebnisse frueherer Spiele). Je Team zaehlt das letzte Spiel derselben Saison (Saisonauftakt = Faktoren 0):
  b2b_h / b2b_a   Heim- bzw. Gastteam spielte am Vortag (Abstand 1 Tag)
  r3_h / r3_a     mindestens 3 Ruhetage (Abstand >= 4 Tage; Variante >= 3 Tage am Ende des Berichts)
  tz_east_a / tz_west_a  Zeitzonen-Wechsel des Gastteams gegenueber dem Ort seines letzten Spiels (Stunden, Ostwaerts = Ort mit spaeterer Uhrzeit); UTC-Versatz am Spieltag (zoneinfo)
  dist_a / dist_h Entfernung (1000 km, Grosskreis) zwischen dem Ort des letzten Spiels und dem Spielort, fuer Gast bzw. Heim
  alt             Heimspiel von Denver oder Utah
Spielorte: feste Koordinaten/Zeitzonen der 30 Heimstaedte (Tabelle unten). Neutral-/Auslandsspiele (ca. 3-5 je Saison, z. B. Mexiko-Stadt, Paris, Berlin, London) sind in den Daten
nicht gekennzeichnet; sie laufen mit der Heimstadt des Heimteams, ihr Reiseanteil ist dort falsch. Nur das Cup-Halbfinale/Finale (ist_stage) wird ausgeschlossen.

Messung je Faktor: OLS-Steigung des Fehlers auf den Faktor mit 95 %-Bootstrap-Intervall (nach Spielen, 2000 Ziehungen), getrennt fuer 2017-2024 zusammen und 2025-26.
Korrektur: mu' = mu + b * x mit b aus 2017-2024; Pruefung auf 2025-26: Brier und Log-Loss gegen heute, gepaarter Bootstrap. Kontrolle: Zwei-Haelften-Regel auf 2025-26
(b auf einer Haelfte lernen, auf der anderen pruefen, und umgekehrt). BESTANDEN = Brier und Log-Loss auf 2025-26 besser (Differenz < 0) UND beide Intervalle unter 0
UND das Steigungs-Intervall 2017-2024 ohne 0. Zusaetzlich gemeinsame Regression aller Faktoren.
"""
import sys
import warnings
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import norm

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from bt_common import load_games, logloss  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import MAX_WIN_PROB, MIN_WIN_PROB  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

OUT = HERE / "reports" / "winner_rest_travel.txt"
B = 2000
SIGMA = lp.SPREAD_SIGMA
TRAIN = range(2017, 2025)
TEST = 2025

# Heimstadt: (Breite, Laenge, IANA-Zeitzone)
VENUES = {
    "Atlanta Hawks": (33.757, -84.396, "America/New_York"), "Boston Celtics": (42.366, -71.062, "America/New_York"),
    "Brooklyn Nets": (40.683, -73.975, "America/New_York"), "Charlotte Hornets": (35.225, -80.839, "America/New_York"),
    "Chicago Bulls": (41.881, -87.674, "America/Chicago"), "Cleveland Cavaliers": (41.496, -81.688, "America/New_York"),
    "Dallas Mavericks": (32.790, -96.810, "America/Chicago"), "Denver Nuggets": (39.749, -105.008, "America/Denver"),
    "Detroit Pistons": (42.341, -83.055, "America/New_York"), "Golden State Warriors": (37.768, -122.388, "America/Los_Angeles"),
    "Houston Rockets": (29.751, -95.362, "America/Chicago"), "Indiana Pacers": (39.764, -86.156, "America/New_York"),
    "LA Clippers": (34.043, -118.267, "America/Los_Angeles"), "Los Angeles Lakers": (34.043, -118.267, "America/Los_Angeles"),
    "Memphis Grizzlies": (35.138, -90.051, "America/Chicago"), "Miami Heat": (25.781, -80.187, "America/New_York"),
    "Milwaukee Bucks": (43.045, -87.917, "America/Chicago"), "Minnesota Timberwolves": (44.980, -93.276, "America/Chicago"),
    "New Orleans Pelicans": (29.949, -90.082, "America/Chicago"), "New York Knicks": (40.751, -73.994, "America/New_York"),
    "Oklahoma City Thunder": (35.463, -97.515, "America/Chicago"), "Orlando Magic": (28.539, -81.384, "America/New_York"),
    "Philadelphia 76ers": (39.901, -75.172, "America/New_York"), "Phoenix Suns": (33.446, -112.071, "America/Phoenix"),
    "Portland Trail Blazers": (45.532, -122.667, "America/Los_Angeles"), "Sacramento Kings": (38.580, -121.500, "America/Los_Angeles"),
    "San Antonio Spurs": (29.427, -98.438, "America/Chicago"), "Toronto Raptors": (43.643, -79.379, "America/New_York"),
    "Utah Jazz": (40.768, -111.901, "America/Denver"), "Washington Wizards": (38.898, -77.021, "America/New_York"),
}
NEUTRAL_STAGES = {"East Semifinal", "West Semifinal", "Championship"}   # NBA-Cup-Endrunde in Las Vegas
ALT_TEAMS = {"Denver Nuggets", "Utah Jazz"}


def km(a, b):
    la1, lo1, la2, lo2 = map(radians, (VENUES[a][0], VENUES[a][1], VENUES[b][0], VENUES[b][1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def utc_off(team, day):
    dt = datetime(day.year, day.month, day.day, 12, tzinfo=ZoneInfo(VENUES[team][2]))
    return dt.utcoffset().total_seconds() / 3600.0


def win_p(mu):
    return np.clip(norm.cdf(np.round(mu, 1) / SIGMA), MIN_WIN_PROB, MAX_WIN_PROB)


def build(games, gap3=4):
    """Faktoren je Spiel (Wissen vor Anpfiff). Rueckgabe: dict Spaltenname -> Array, ausserdem 'neutral'."""
    n = len(games)
    cols = {k: np.zeros(n) for k in ("b2b_h", "b2b_a", "r3_h", "r3_a", "tz_east_a", "tz_west_a", "dist_a", "dist_h", "alt", "neutral")}
    last = {}                                            # Team -> (Datum, Saison, Ort)
    for i, g in enumerate(games):
        h, a, s = g["home_team"]["full_name"], g["visitor_team"]["full_name"], g["season"]
        d = datetime.strptime(g["date"][:10], "%Y-%m-%d").date()
        neutral = g.get("ist_stage") in NEUTRAL_STAGES
        cols["neutral"][i] = neutral
        cols["alt"][i] = h in ALT_TEAMS
        for side, t in (("h", h), ("a", a)):
            prev = last.get(t)
            if prev is None or prev[1] != s:
                continue                                  # Saisonauftakt: keine Faktoren
            dd = (d - prev[0]).days
            cols[f"b2b_{side}"][i] = dd == 1
            cols[f"r3_{side}"][i] = dd >= gap3
            loc = prev[2]
            if loc is not None and not neutral:
                cols[f"dist_{side}"][i] = km(loc, h) / 1000.0
                if side == "a":
                    shift = utc_off(h, d) - utc_off(loc, d)
                    cols["tz_east_a"][i] = max(shift, 0.0)
                    cols["tz_west_a"][i] = max(-shift, 0.0)
        loc_now = None if neutral else h
        last[h] = (d, s, loc_now)
        last[a] = (d, s, loc_now)
    return cols


def ols(X, y):
    A = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta                                           # [Achsenabschnitt, Steigungen ...]


def boot_beta(X, y, seed):
    rng = np.random.default_rng(seed)
    n = len(y)
    out = []
    for _ in range(B):
        i = rng.integers(0, n, n)
        out.append(ols(X[i], y[i]))
    return np.array(out)


def ci(v):
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def metric_diffs(mu, mu2, y):
    p0, p1 = win_p(mu), win_p(mu2)
    return (p1 - y) ** 2 - (p0 - y) ** 2, logloss(p1, y) - logloss(p0, y)


def boot_mean(d, seed):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (B, len(d)))
    return float(d.mean()), *ci(d[idx].mean(axis=1))


def correct(mu, X, b):
    return mu + X @ b


def evaluate(mu, X, y, b, seed):
    db, dl = metric_diffs(mu, correct(mu, X, b), y)
    return boot_mean(db, seed), boot_mean(dl, seed + 1)


FACT_NAMES = {
    "b2b_h": "Heim Back-to-Back", "b2b_a": "Gast Back-to-Back", "r3_h": "Heim >= 3 Ruhetage", "r3_a": "Gast >= 3 Ruhetage",
    "tz_east_a": "Gast: Zeitzone ostwaerts (je Stunde)", "tz_west_a": "Gast: Zeitzone westwaerts (je Stunde)",
    "dist_a": "Gast: Entfernung zum letzten Ort (je 1000 km)", "dist_h": "Heim: Entfernung zum letzten Ort (je 1000 km, zusaetzlich)",
    "alt": "Hoehenlage (Heimspiel Denver/Utah)",
}
ORDER = list(FACT_NAMES)

# ------------------------------------------------------------------------------------------------- Daten
games = load_games(2015, 2025)
rows, _, _, _ = rt.run(games, K=20.0, hca=100.0, mov="cur")
F = build(games)
season, post = rows["season"], rows["post"]
mu_all = rows["diff"] / 50.0
margin_all = rows["margin"]
keep = (post == 0) & (F["neutral"] == 0)
err_all = margin_all - mu_all
win_all = (margin_all > 0).astype(float)


def sel(mask):
    return {k: v[mask] for k, v in F.items()}, mu_all[mask], margin_all[mask], err_all[mask], win_all[mask]


tr_mask = keep & np.isin(season, list(TRAIN))
te_mask = keep & (season == TEST)
Ftr, mu_tr, mg_tr, e_tr, w_tr = sel(tr_mask)
Fte, mu_te, mg_te, e_te, w_te = sel(te_mask)
n_tr, n_te = int(tr_mask.sum()), int(te_mask.sum())


def mat(Fd, names):
    return np.column_stack([Fd[k] for k in names])


lines = []
P = lines.append
P("RUHETAGE, REISE, HOEHENLAGE IM SIEGER-MODELL (Spread und Siegchance)")
P(f"Messskript: analysis/backtest_winner_rest_travel.py (liest nur data/cache). Replay: analysis/replica_tunable.run, Modell von heute (K 20, Heimvorteil 100, MoV heute, Ruhe -1,5/+0,45 ELO).")
P(f"Fehler = Ist-Spread minus Modell-Spread (Heim-Sicht, + = Heim besser als Modell), nur Regular Season ohne Cup-Endrunde (Las Vegas). Spiele: 2017-2024 {n_tr}, 2025-26 {n_te}.")
P(f"Mittlerer Fehler: 2017-2024 {e_tr.mean():+.2f} Punkte (Std {e_tr.std():.1f}), 2025-26 {e_te.mean():+.2f} (Std {e_te.std():.1f}). Siegchance wie heute (Normalverteilung, Sigma {SIGMA}, 3-97 %).")
P("Brier/Log-Loss-Differenzen sind NEU minus HEUTE in x10^-3 (negativ = besser), Intervalle 95 % (gepaarter Bootstrap nach Spielen, 2000 Ziehungen).")
P("")

# ------------------------------------------------------------------------------------------------- 1 Haeufigkeit und Gruppenmittel
P("1 HAEUFIGKEIT UND MITTLERER FEHLER JE GRUPPE (Faktor = 1 bzw. > 0)")
P(f"  {'Faktor':58s} {'2017-24: n':>10s} {'Fehler Pkt':>11s} {'2025-26: n':>10s} {'Fehler Pkt':>11s}")
for k in ORDER:
    m1, m2 = Ftr[k] > 0, Fte[k] > 0
    P(f"  {FACT_NAMES[k]:58s} {m1.sum():10d} {e_tr[m1].mean() if m1.sum() else float('nan'):+11.2f} {m2.sum():10d} {e_te[m2].mean() if m2.sum() else float('nan'):+11.2f}")
P("")

# ------------------------------------------------------------------------------------------------- 2 Einzelfaktoren
P("2 EINZELFAKTOREN: Steigung (Punkte je Faktor-Einheit) mit 95-%-Intervall, Korrektur aus 2017-2024, Pruefung 2025-26")
single = {}
for j, k in enumerate(ORDER):
    xtr, xte = Ftr[k][:, None], Fte[k][:, None]
    b_tr = ols(xtr, e_tr)[1]
    bs_tr = boot_beta(xtr, e_tr, 100 + j)[:, 1]
    b_te = ols(xte, e_te)[1]
    bs_te = boot_beta(xte, e_te, 200 + j)[:, 1]
    per_season = []
    for s in TRAIN:
        mk = (season[tr_mask] == s)
        per_season.append(ols(xtr[mk], e_tr[mk])[1])
    same_sign = int(sum(np.sign(v) == np.sign(b_tr) for v in per_season))
    (mb, blo, bhi), (ml, llo, lhi) = evaluate(mu_te, xte, w_te, np.array([b_tr]), 300 + j)
    # Zwei-Haelften auf 2025-26 (Fehler e_te, Siegindikator w_te)
    n = len(e_te); h1, h2 = np.arange(n) < n // 2, np.arange(n) >= n // 2
    hres, dbs, dls = [], [], []
    for a_, b_ in ((h1, h2), (h2, h1)):
        bh = ols(xte[a_], e_te[a_])[1]
        db, dl = metric_diffs(mu_te[b_], mu_te[b_] + xte[b_, 0] * bh, w_te[b_])
        hres.append((db.mean(), dl.mean(), bh)); dbs.append(db); dls.append(dl)
    hb = boot_mean(np.concatenate(dbs), 400 + j); hl = boot_mean(np.concatenate(dls), 500 + j)
    train_sig = not (ci(bs_tr)[0] <= 0 <= ci(bs_tr)[1])
    passed = (mb < 0 and ml < 0 and bhi < 0 and lhi < 0 and train_sig)
    half_ok = all(r[0] < 0 and r[1] < 0 for r in hres)
    single[k] = dict(b=b_tr, ci=ci(bs_tr), b_te=b_te, ci_te=ci(bs_te), per_season=per_season, same_sign=same_sign, brier=(mb, blo, bhi), ll=(ml, llo, lhi),
                     halves=hres, hb=hb, hl=hl, passed=passed, half_ok=half_ok, train_sig=train_sig)
    P(f"  {FACT_NAMES[k]}")
    P(f"    Steigung 2017-24: {b_tr:+.2f} Pkt [{ci(bs_tr)[0]:+.2f}; {ci(bs_tr)[1]:+.2f}] (Vorzeichen gleich in {same_sign} von 8 Einzelsaisons: " + ", ".join(f"{v:+.1f}" for v in per_season) + ")")
    P(f"    Steigung 2025-26: {b_te:+.2f} Pkt [{ci(bs_te)[0]:+.2f}; {ci(bs_te)[1]:+.2f}]")
    P(f"    Pruefung 2025-26 mit b aus 2017-24: Brier {mb*1000:+.2f} [{blo*1000:+.2f}; {bhi*1000:+.2f}], Log-Loss {ml*1000:+.2f} [{llo*1000:+.2f}; {lhi*1000:+.2f}]")
    P(f"    Zwei Haelften 2025-26 (A->B / B->A): Brier {hres[0][0]*1000:+.2f} / {hres[1][0]*1000:+.2f}, Log-Loss {hres[0][1]*1000:+.2f} / {hres[1][1]*1000:+.2f}; gemeinsam Brier {hb[0]*1000:+.2f} [{hb[1]*1000:+.2f}; {hb[2]*1000:+.2f}], Log-Loss {hl[0]*1000:+.2f} [{hl[1]*1000:+.2f}; {hl[2]*1000:+.2f}] -> auf beiden Haelften besser: {'ja' if half_ok else 'nein'}")
    P(f"    => {'BESTANDEN' if passed else 'nicht bestanden'} (Brier/Log-Loss besser: {'ja' if mb < 0 and ml < 0 else 'nein'}; Intervalle Pruefung < 0: {'ja' if bhi < 0 and lhi < 0 else 'nein'}; Steigungs-Intervall 2017-24 ohne 0: {'ja' if train_sig else 'nein'})")
P("")

# ------------------------------------------------------------------------------------------------- 3 Gemeinsame Regression
P("3 GEMEINSAME REGRESSION (alle Faktoren zusammen, damit nichts doppelt zaehlt)")
Xtr, Xte = mat(Ftr, ORDER), mat(Fte, ORDER)
beta_tr = ols(Xtr, e_tr)
bsb_tr = boot_beta(Xtr, e_tr, 900)
beta_te = ols(Xte, e_te)
bsb_te = boot_beta(Xte, e_te, 901)
P(f"  {'Faktor':58s} {'2017-24 Steigung [95 %]':>28s} {'2025-26 Steigung [95 %]':>28s}   Einzel 2017-24")
for j, k in enumerate(ORDER):
    c1, c2 = ci(bsb_tr[:, j + 1]), ci(bsb_te[:, j + 1])
    mark = "*" if not (c1[0] <= 0 <= c1[1]) else " "
    P(f"  {FACT_NAMES[k]:58s} {beta_tr[j+1]:+7.2f} [{c1[0]:+6.2f}; {c1[1]:+6.2f}]{mark} {beta_te[j+1]:+7.2f} [{c2[0]:+6.2f}; {c2[1]:+6.2f}]   {single[k]['b']:+.2f}")
P("  (* = Intervall 2017-24 ohne 0; Achsenabschnitt: " + f"{beta_tr[0]:+.2f} / {beta_te[0]:+.2f} Pkt)")
b_all = beta_tr[1:]
(gb, glo, ghi), (gl, gllo, glhi) = evaluate(mu_te, Xte, w_te, b_all, 910)
P(f"  Pruefung 2025-26, alle Faktoren mit b aus 2017-24: Brier {gb*1000:+.2f} [{glo*1000:+.2f}; {ghi*1000:+.2f}], Log-Loss {gl*1000:+.2f} [{gllo*1000:+.2f}; {glhi*1000:+.2f}]")
sig = [j for j, k in enumerate(ORDER) if not (ci(bsb_tr[:, j + 1])[0] <= 0 <= ci(bsb_tr[:, j + 1])[1])]
if sig:
    Xs_tr, Xs_te = Xtr[:, sig], Xte[:, sig]
    bred = ols(Xs_tr, e_tr)
    (rb, rlo, rhi), (rl, rllo, rlhi) = evaluate(mu_te, Xs_te, w_te, bred[1:], 920)
    P(f"  Nur Faktoren mit Intervall ohne 0 ({', '.join(ORDER[j] for j in sig)}), neu geschaetzt: " + ", ".join(f"{ORDER[j]} {bred[1+i]:+.2f}" for i, j in enumerate(sig)))
    P(f"    Pruefung 2025-26: Brier {rb*1000:+.2f} [{rlo*1000:+.2f}; {rhi*1000:+.2f}], Log-Loss {rl*1000:+.2f} [{rllo*1000:+.2f}; {rlhi*1000:+.2f}]")
    n = len(e_te); h1, h2 = np.arange(n) < n // 2, np.arange(n) >= n // 2
    dbs, dls, hr = [], [], []
    for a_, b_ in ((h1, h2), (h2, h1)):
        bh = ols(Xs_te[a_], e_te[a_])[1:]
        db, dl = metric_diffs(mu_te[b_], mu_te[b_] + Xs_te[b_] @ bh, w_te[b_])
        dbs.append(db); dls.append(dl); hr.append((db.mean(), dl.mean()))
    hb = boot_mean(np.concatenate(dbs), 930); hl = boot_mean(np.concatenate(dls), 931)
    P(f"    Zwei Haelften 2025-26 (A->B / B->A): Brier {hr[0][0]*1000:+.2f} / {hr[1][0]*1000:+.2f}, Log-Loss {hr[0][1]*1000:+.2f} / {hr[1][1]*1000:+.2f}; gemeinsam Brier {hb[0]*1000:+.2f} [{hb[1]*1000:+.2f}; {hb[2]*1000:+.2f}], Log-Loss {hl[0]*1000:+.2f} [{hl[1]*1000:+.2f}; {hl[2]*1000:+.2f}]")
else:
    P("  Kein Faktor hat in der gemeinsamen Regression 2017-24 ein Intervall ohne 0; keine verkleinerte Variante.")
# Zwei Haelften fuer alle Faktoren gemeinsam
n = len(e_te); h1, h2 = np.arange(n) < n // 2, np.arange(n) >= n // 2
dbs, dls, hr = [], [], []
for a_, b_ in ((h1, h2), (h2, h1)):
    bh = ols(Xte[a_], e_te[a_])[1:]
    db, dl = metric_diffs(mu_te[b_], mu_te[b_] + Xte[b_] @ bh, w_te[b_])
    dbs.append(db); dls.append(dl); hr.append((db.mean(), dl.mean()))
hb = boot_mean(np.concatenate(dbs), 940); hl = boot_mean(np.concatenate(dls), 941)
P(f"  Zwei Haelften 2025-26, alle Faktoren (A->B / B->A): Brier {hr[0][0]*1000:+.2f} / {hr[1][0]*1000:+.2f}, Log-Loss {hr[0][1]*1000:+.2f} / {hr[1][1]*1000:+.2f}; gemeinsam Brier {hb[0]*1000:+.2f} [{hb[1]*1000:+.2f}; {hb[2]*1000:+.2f}], Log-Loss {hl[0]*1000:+.2f} [{hl[1]*1000:+.2f}; {hl[2]*1000:+.2f}] (viele Parameter auf je ~600 Spielen: Ueberanpassung moeglich)")
P("")

# ------------------------------------------------------------------------------------------------- 4 Variante Ruhetage
P("4 VARIANTE: 'viel Ruhe' ab Abstand >= 3 Tagen (2 Ruhetage, wie im Modell) statt >= 4")
F3 = build(games, gap3=3)
F3tr = {k: v[tr_mask] for k, v in F3.items()}; F3te = {k: v[te_mask] for k, v in F3.items()}
for k in ("r3_h", "r3_a"):
    x1, x2 = F3tr[k][:, None], F3te[k][:, None]
    b = ols(x1, e_tr)[1]; c = ci(boot_beta(x1, e_tr, 1000)[:, 1])
    (mb, blo, bhi), (ml, llo, lhi) = evaluate(mu_te, x2, w_te, np.array([b]), 1010)
    P(f"  {FACT_NAMES[k].replace('3 Ruhetage','2 Ruhetage')}: n {int(x1.sum())}/{int(x2.sum())}, Steigung 2017-24 {b:+.2f} [{c[0]:+.2f}; {c[1]:+.2f}], Pruefung 2025-26 Brier {mb*1000:+.2f} [{blo*1000:+.2f}; {bhi*1000:+.2f}], Log-Loss {ml*1000:+.2f} [{llo*1000:+.2f}; {lhi*1000:+.2f}]")
P("")

# ------------------------------------------------------------------------------------------------- 5 Hoehe getrennt
P("5 HOEHENLAGE GETRENNT")
for t in sorted(ALT_TEAMS):
    mk_tr = np.array([g["home_team"]["full_name"] == t for g in games])[tr_mask]; mk_te = np.array([g["home_team"]["full_name"] == t for g in games])[te_mask]
    x1, x2 = mk_tr.astype(float)[:, None], mk_te.astype(float)[:, None]
    b = ols(x1, e_tr)[1]; c = ci(boot_beta(x1, e_tr, 1100)[:, 1]); b2 = ols(x2, e_te)[1]; c2 = ci(boot_beta(x2, e_te, 1101)[:, 1])
    P(f"  {t}: n {int(mk_tr.sum())}/{int(mk_te.sum())}, Steigung 2017-24 {b:+.2f} [{c[0]:+.2f}; {c[1]:+.2f}], 2025-26 {b2:+.2f} [{c2[0]:+.2f}; {c2[1]:+.2f}] (Hinweis: Denver/Utah haben auch ohne Hoehe oft starke Heimbilanzen, die Ratings enthalten schon einen Teil davon)")
P("")

# ------------------------------------------------------------------------------------------------- Zusammenfassung
P("ZUSAMMENFASSUNG")
bestanden = [FACT_NAMES[k] for k in ORDER if single[k]["passed"]]
P("  Einzelfaktoren bestanden: " + (", ".join(bestanden) if bestanden else "keiner"))
P("  Steigungs-Intervall 2017-24 ohne 0 (unabhaengig von der Pruefung): " + (", ".join(FACT_NAMES[k] for k in ORDER if single[k]["train_sig"]) or "keiner"))
P("  Beide Haelften 2025-26 besser (Brier und Log-Loss): " + (", ".join(FACT_NAMES[k] for k in ORDER if single[k]["half_ok"]) or "keiner"))
P(f"  Alle Faktoren gemeinsam, Pruefung 2025-26: Brier {gb*1000:+.2f} [{glo*1000:+.2f}; {ghi*1000:+.2f}], Log-Loss {gl*1000:+.2f} [{gllo*1000:+.2f}; {glhi*1000:+.2f}]")
P("  Grenzen: Auslands-/Neutralplatzspiele sind nicht erkennbar (Reisewerte dort falsch); Ruhetage zaehlen auch Pausen wie All-Star; 'Saisonauftakt' bekommt Faktor 0;")
P("  Modell-Spread ist das reine Elo-Modell (ohne Markt-Mischung und ohne Verletzungen). Das Modell enthaelt Ruhetage bereits mit -1,5/+0,45 ELO (0,03/0,009 Punkte), das ist vernachlaessigbar.")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))

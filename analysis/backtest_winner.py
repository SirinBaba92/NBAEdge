"""
Sieger-Modell (Moneyline) Ist-Stand, Saison 2025-26, Walk-forward. NUR LESEND: liest data/cache (games_2015 bis games_2025), schreibt nur analysis/reports/winner_2025-26.txt.
Keine API-Calls, Produktivcode und Produktivdateien bleiben unveraendert. Gemessen wird nichts an Quoten, nur an echten Ergebnissen (Sieger inkl. Verlaengerung).

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_winner.py

Verfahren (wie analysis/backtest_team_markets.py, dessen Bausteine wiederverwendet werden): Replay der produktiven ELO-Engine ueber alle Spiele ab 2015 (analysis/replica_tunable.run,
Produktivparameter); vor jedem Spiel steht nur das Wissen davor (Ratings, Form, Ruhetage). Spread-Mittelwert = diff / 50, Siegchance Heim = engine.line_probabilities.win_prob_home(round(Spread, 1))
(Normalverteilung, Sigma 13,2, begrenzt auf 3-97 %), also die Zahl, die die App OHNE Markt-Mischung zeigt. Hauptauswertung Regular Season; Playoffs getrennt als Zusatz.
Phase: "erste 15" = beide Teams haben vor dem Spiel weniger als 15 Spiele (gp_h, gp_a < 15), "danach" = alle uebrigen. Intervalle: Bootstrap nach Spielen, 95 %, 2000 Ziehungen.
"""
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from bt_common import load_games, logloss  # noqa: E402
import replica_tunable as rt  # noqa: E402
from config.settings import ELO_TO_SPREAD_FACTOR  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402

OUT = HERE / "reports" / "winner_2025-26.txt"
SEASON = 2025
PRODUCTION = dict(K=20.0, hca=100.0, mov="cur", total_alpha=0.1)
FIRST_N = 15
B = 2000


def boot(v, seed=0):
    v = np.asarray(v, float)
    idx = np.random.default_rng(seed).integers(0, len(v), (B, len(v)))
    m = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def metrics(p, y):
    fav = np.where(p >= 0.5, 1.0, 0.0)
    return {"n": len(p), "brier": boot((p - y) ** 2, 1), "ll": boot(logloss(p, y), 2), "fav": boot((fav == y).astype(float), 3),
            "p_home": float(p.mean()), "home_rate": float(y.mean()), "diff": boot(p - y, 4)}


def pct(x, d=1):
    return f"{100 * x:.{d}f}"


def calib_rows(p, y, step=0.05):
    edges = np.round(np.arange(0.0, 1.0 + 1e-9, step), 4)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
        if m.sum():
            rows.append((lo, hi, int(m.sum()), float(p[m].mean()), float(y[m].mean())))
    return rows


def fav_rows(p, y, step=0.05):
    q, hit = np.maximum(p, 1 - p), np.where(p >= 0.5, y, 1 - y)
    edges = np.round(np.arange(0.5, 1.0 + 1e-9, step), 4)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (q >= lo) & ((q < hi) if hi < 1.0 else (q <= hi))
        if m.sum():
            rows.append((lo, hi, int(m.sum()), float(q[m].mean()), float(hit[m].mean())))
    return rows


def table(rows, title, low_n=20):
    out = [title, f"  {'Stufe':>10}{'Spiele':>8}{'Ø Modell %':>12}{'Trefferquote %':>16}{'Abw. PP':>10}   Hinweis"]
    for lo, hi, n, pm, hr in rows:
        out.append(f"  {pct(lo, 0) + '-' + pct(hi, 0) + ' %':>10}{n:>8}{pct(pm):>12}{pct(hr):>16}{100 * (hr - pm):>+10.1f}   {'wenige Spiele (n < ' + str(low_n) + ')' if n < low_n else ''}")
    return out


def block(name, p, y):
    m = metrics(p, y)
    ci = lambda t, f=lambda x: f"{x:.4f}": f"{f(t[0])} [{f(t[1])}; {f(t[2])}]"
    pc = lambda t: f"{pct(t[0])} % [{pct(t[1])}; {pct(t[2])}]"
    d = m["diff"]
    return m, [f"{name}", f"  Spiele: {m['n']}",
               f"  Brier-Score: {ci(m['brier'])}   (Referenz immer 50 %: 0,2500; kleiner ist besser)",
               f"  Log-Loss:    {ci(m['ll'])}   (Referenz immer 50 %: 0,6931)",
               f"  Favorit gewinnt: {pc(m['fav'])}",
               f"  Heimvorteil: Ø Modell-Chance Heim {pct(m['p_home'])} % gegen tatsächliche Heim-Siegquote {pct(m['home_rate'])} %  (Differenz Modell minus Ist {100 * d[0]:+.1f} PP [{100 * d[1]:+.1f}; {100 * d[2]:+.1f}])"]


def main():
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **PRODUCTION)
    sel = np.where(rows["season"] == SEASON)[0]
    mu = rows["diff"][sel] / ELO_TO_SPREAD_FACTOR
    p = np.array([lp.win_prob_home(round(float(x), 1)) for x in mu])
    y = (rows["margin"][sel] > 0).astype(float)
    post, gh, ga = rows["post"][sel].astype(int), rows["gp_h"][sel], rows["gp_a"][sel]
    dates = [games[i]["date"][:10] for i in sel]
    chron = all(dates[i] <= dates[i + 1] for i in range(len(dates) - 1))
    # Kausalitaet: Replay nur bis Spiel i (ohne Spiel i und Zukunft) liefert dieselbe Differenz wie der volle Lauf
    pos = np.linspace(0, len(sel) - 1, 6).astype(int)
    worst = 0.0
    for k in pos:
        i = int(sel[k])
        part, _, _, _ = rt.run(games[:i + 1], **PRODUCTION)
        worst = max(worst, abs(float(part["diff"][i]) - float(rows["diff"][i])))
        part2, _, _, _ = rt.run(games[:i], **PRODUCTION)
        worst = max(worst, float(np.max(np.abs(part2["diff"][:i] - rows["diff"][:i]))) if i else 0.0)
    rs = post == 0
    first = rs & (gh < FIRST_N) & (ga < FIRST_N)
    later = rs & ~first
    L = []
    w = L.append
    w(f"SIEGER-MODELL (MONEYLINE), IST-STAND, SAISON 2025-26 — erstellt {datetime.now():%Y-%m-%d %H:%M} (analysis/backtest_winner.py)")
    w("Gemessen wird das REINE MODELL ohne Markt-Mischung (die App mischt den Markt zum Spread mit 25 % dazu; historische Linien gibt es nicht) und nur gegen echte Ergebnisse, keine Quoten.")
    w("Siegchance = Normalverteilung um den Spread (ELO-Differenz / 50) mit Sigma 13,2, begrenzt auf 3-97 %, genau die Rechnung der App (engine/line_probabilities.win_prob_home).")
    w(f"Walk-forward: Replay der Produktiv-Engine ab 2015, vor jedem Spiel nur Wissen davor. Kausalitätsprüfung (Replay nur bis Spiel i-1 bzw. i gegen den vollen Lauf, 6 Stichproben): größte Abweichung {worst:.2e}; Spiele chronologisch: {'ja' if chron else 'NEIN'}.")
    w(f"Spiele 2025-26 im Replay: {len(sel)} (Regular Season {int(rs.sum())}, Playoffs {int((post == 1).sum())}). Spiele mit Verlängerung zählen als normaler Sieg/Niederlage.")
    w("Einschränkung: Sigma 13,2, K, Heimvorteil und MOV-Faktor wurden früher an Daten bis einschließlich 2025 festgelegt (Sigma auf 2017-2025). 2025-26 ist deshalb nicht völlig 'ungesehen'; da es nur wenige Parameter sind, ist der Effekt klein, aber nicht null.")
    w("")
    mm, lines = block("1. GESAMT (Regular Season)", p[rs], y[rs])
    L += lines
    w("")
    L += table(calib_rows(p[rs], y[rs]), "2. KALIBRIERUNG in 5-%-Stufen (Heim-Siegchance des Modells, Regular Season)")
    w("")
    L += table(fav_rows(p[rs], y[rs]), "   Favoriten-Sicht (Chance der favorisierten Seite, Trefferquote des Favoriten je Stufe)")
    w("")
    w("3. HEIMVORTEIL")
    d = mm["diff"]
    w(f"  Ø Modell-Chance Heim {pct(mm['p_home'])} %, tatsächliche Heim-Siegquote {pct(mm['home_rate'])} % ({int(y[rs].sum())} von {int(rs.sum())}). "
      f"Differenz {100 * d[0]:+.1f} PP, 95 %-Intervall [{100 * d[1]:+.1f}; {100 * d[2]:+.1f}] ({'0 liegt im Intervall: keine Verzerrung nachweisbar' if d[1] <= 0 <= d[2] else '0 liegt NICHT im Intervall'}).")
    w("")
    w(f"4. SAISONPHASE (Regular Season): erste {FIRST_N} Spiele je Team (beide Teams < {FIRST_N} Spiele) gegen danach")
    for nm, mk in ((f"erste {FIRST_N}", first), ("danach", later)):
        _, ln = block(f"  [{nm}]", p[mk], y[mk])
        L += ln
        w("")
    for nm, mk in ((f"erste {FIRST_N}", first), ("danach", later)):
        L += table(calib_rows(p[mk], y[mk], 0.10), f"  Kalibrierung [{nm}] in 10-%-Stufen (5-%-Stufen sind je Phase zu dünn besetzt)", low_n=20)
        w("")
    w("5. TREFFERQUOTE DES FAVORITEN")
    for nm, mk in (("Regular Season gesamt", rs), (f"erste {FIRST_N}", first), ("danach", later)):
        t = boot((np.where(p[mk] >= 0.5, 1.0, 0.0) == y[mk]).astype(float), 3)
        w(f"  {nm:<24} n {int(mk.sum()):>5}  Favorit gewinnt {pct(t[0])} % [{pct(t[1])}; {pct(t[2])}]")
    hv = p[rs] >= 0.5
    w(f"  Favorit = Heimteam in {int(hv.sum())} Spielen: gewinnt {pct(y[rs][hv].mean())} %; Favorit = Gastteam in {int((~hv).sum())} Spielen: gewinnt {pct(1 - y[rs][~hv].mean())} %.")
    w("")
    w("ZUSATZ: Playoffs 2025-26 (getrennt, kleine Stichprobe)")
    po = post == 1
    if po.sum():
        _, ln = block("  Playoffs", p[po], y[po])
        L += ln
    w("")
    w("Hinweis: reine Messung, keine Empfehlung und keine Änderung am Modell.")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

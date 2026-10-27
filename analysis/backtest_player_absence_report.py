"""
Auswertung zu Ausfaellen von Stammspielern (Zwischenstaende von analysis/backtest_player_absence.py). NUR LESEND, schreibt nur analysis/reports/player_absence.txt.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_absence_report.py
Alle Intervalle (95 %): Bootstrap NACH SPIELEN (beide Teams eines Spiels zusammen), 600 Ziehungen. Gruppen/Stufen mit unter 100 Zeilen sind gekennzeichnet.
"""
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
TMP = Path("/private/tmp/claude-501/-Users-baranalturk-Desktop-NBAEdge/76ad3d4f-3f38-4b80-9c53-3d58597b513a/scratchpad/pa")
OUT = HERE / "reports" / "player_absence.txt"
SEASONS = ["2024-25", "2025-26"]
NB = 600
FIXED_K = [10, 15, 20, 25]
AROUND = [-2, -1, 0, 1, 2]

L = []
P = L.append


# ------------------------------------------------------------------------------------------------ Daten
def load_all():
    R, T = {}, {}
    g_off = tg_off = 0
    parts_r, parts_t, pa, pb, pc = [], [], [], [], []
    for s in SEASONS:
        d = np.load(TMP / f"{s}.npz")
        r = {k[2:]: d[k] for k in d.files if k.startswith("r_")}
        t = {k[2:]: d[k] for k in d.files if k.startswith("t_")}
        r["gid"] = r["gi"] + g_off; r["tgg"] = r["tg"] + tg_off; r["season"] = np.full(len(r["gi"]), s)
        t["gid"] = t["gi"] + g_off; t["tgg"] = t["tg"] + tg_off; t["season"] = np.full(len(t["gi"]), s)
        g_off += int(d["n_games_total"][0]); tg_off += len(t["tg"])
        parts_r.append(r); parts_t.append(t); pa.append(d["pA"]); pb.append(d["pB"]); pc.append(d["pC"])
    R = {k: np.concatenate([p[k] for p in parts_r]) for k in parts_r[0]}
    T = {k: np.concatenate([p[k] for p in parts_t]) for k in parts_t[0]}
    return R, T, np.concatenate(pa), np.concatenate(pb), np.concatenate(pc), g_off, tg_off


R, T, PA, PB, PC, G, NTG = load_all()
NR = len(R["gid"])
_r = np.random.default_rng(7)
W = np.stack([np.bincount(_r.integers(0, G, G), minlength=G) for _ in range(NB)]).astype(float)


def gs_r(x, mask):
    return np.bincount(R["gid"][mask], weights=x[mask], minlength=G)


def gs_t(x, mask):
    return np.bincount(T["gid"][mask], weights=x[mask], minlength=G)


def ci_ratio(num, den):
    if den.sum() == 0:
        return (np.nan,) * 3
    bs = (W @ num) / np.maximum(W @ den, 1e-12)
    return float(num.sum() / den.sum()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def ci_diff(n1, d1, n0, d0):
    """Verhaeltnis 1 minus Verhaeltnis 0, Bootstrap gemeinsam."""
    if d1.sum() == 0 or d0.sum() == 0:
        return (np.nan,) * 3
    pt = n1.sum() / d1.sum() - n0.sum() / d0.sum()
    bs = (W @ n1) / np.maximum(W @ d1, 1e-12) - (W @ n0) / np.maximum(W @ d0, 1e-12)
    return float(pt), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def f2(t, d=2):
    return "n/a" if not np.isfinite(t[0]) else f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]"


def f2u(t, d=2):
    return "n/a" if not np.isfinite(t[0]) else f"{t[0]:.{d}f} [{t[1]:.{d}f}; {t[2]:.{d}f}]"


# Mannschaftsspiel-Ebene
n_abs, top3, fresh = T["n_abs"], T["abs_top3"], T["abs_fresh"]
rows_per_tg = np.bincount(R["tgg"], minlength=NTG)
valid_tg = rows_per_tg > 0
CTL = valid_tg & (n_abs == 0)
CASE = valid_tg & (n_abs >= 1)
tg_half = np.zeros(NTG, int)
tg_half[R["tgg"]] = R["half"]
ROLE = np.where(R["rank"] <= 5, 0, np.where(R["rank"] <= 9, 1, 2))          # 0 Starter, 1 Rotation, 2 uebrige
RNAME = ["Starter (Top 5)", "Rotation (6-9)", "uebrige (10+)"]
in_case_r = CASE[R["tgg"]]
in_ctl_r = CTL[R["tgg"]]


def tg_sum(x_r, mask_r=None):
    m = np.ones(NR, bool) if mask_r is None else mask_r
    return np.bincount(R["tgg"][m], weights=x_r[m], minlength=NTG)


err_min = {X: R["min"] - R[f"emin_{X}"] for X in "ABC"}
err_pts = {X: R["pts"] - R[f"epts_{X}"] for X in "ABC"}

# ------------------------------------------------------------------------------------------------ Kopf
P("AUSFAELLE VON STAMMSPIELERN: WIRKUNG AUF DIE MITSPIELER UND GUETE DER HEUTIGEN NEUBERECHNUNG (2024-25 und 2025-26, walk-forward, nur echte Boxscores)")
P("Skripte analysis/backtest_player_absence.py (Replay) und analysis/backtest_player_absence_report.py (Auswertung); beide lesen nur. Obergrenze: wer fehlte, ist Wissen aus der Zukunft (im Betrieb waere nur Gemeldetes bekannt).")
P("Ausgefallen = Spieler der Top 8 des Teams nach Minuten der laufenden Saison bis dahin (ab dem 11. Teamspiel), der im Spiel 0 Minuten hat oder keine Zeile (Teamwechsel danach zaehlt nicht). 'frisch' = spielte im vorigen Teamspiel.")
P("A = rohe Prognose, B = Teamabgleich OHNE Ausfaelle ('ohne Ausfaelle gerechnet'), C = Teamabgleich MIT den Ausfaellen (heutige Neuberechnung: Minuten proportional zu den erwarteten Minuten, Punkte ueber den Teamfaktor proportional zu den erwarteten Punkten).")
P("Bewertet werden nur Spieler mit Prognose UND Minuten > 0. Fehler = Ist minus Prognose. Kontrolle ('ohne Ausfall') = Team-Spiele ab dem 11. Teamspiel ohne Ausgefallenen.")
P("")

# ------------------------------------------------------------------------------------------------ 1 Faelle
P("1 FAELLE")
P(f"  {'Gruppe':44s} {'Team-Spiele':>11s} {'Spiele':>7s} {'Spielerzeilen':>14s}")


def case_line(nm, mk):
    games = len(np.unique(T["gid"][mk]))
    rows = int(mk[R["tgg"]].sum())
    P(f"  {nm:44s} {int(mk.sum()):11d} {games:7d} {rows:14d}" + ("   (< 100 Zeilen: nicht aussagekraeftig)" if rows < 100 else ""))


for s in SEASONS:
    sm = T["season"] == s
    case_line(f"{s}: alle Team-Spiele ab 11. Teamspiel", valid_tg & sm)
    case_line(f"{s}: mit mindestens 1 Ausfall", CASE & sm)
case_line("beide Saisons: alle Team-Spiele", valid_tg)
case_line("beide Saisons: ohne Ausfall (Kontrolle)", CTL)
case_line("beide Saisons: mit mindestens 1 Ausfall", CASE)
case_line("   genau 1 Ausfall", CASE & (n_abs == 1))
case_line("   genau 2 Ausfaelle", CASE & (n_abs == 2))
case_line("   3 oder mehr Ausfaelle", CASE & (n_abs >= 3))
case_line("   mindestens ein Top-3-Spieler fehlt", CASE & (top3 == 1))
case_line("   nur Platz 4-8 fehlt", CASE & (top3 == 0))
case_line("   mindestens ein 'frisch' Ausgefallener", CASE & (fresh == 1))
case_line("   nur laenger Fehlende", CASE & (fresh == 0))
case_line("   1 Ausfall, Top 3", CASE & (n_abs == 1) & (top3 == 1))
case_line("   1 Ausfall, Platz 4-8", CASE & (n_abs == 1) & (top3 == 0))
nspiele = len(np.unique(T["gid"][CASE]))
P(f"  => {int(CASE.sum())} Team-Spiele mit Ausfall in {nspiele} Spielen ({int(in_case_r.sum())} Spielerzeilen); Kontrolle {int(CTL.sum())} Team-Spiele ({int(in_ctl_r.sum())} Zeilen).")
P("")

# ------------------------------------------------------------------------------------------------ 2 Wirkung
P("2 WIRKUNG AUF DIE MITSPIELER (roh, Variante A: Ist minus Prognose je Mitspieler)")
P(f"  {'Gruppe':44s} {'Zeilen':>7s} {'Minuten Ø [95 %]':>22s} {'Punkte Ø [95 %]':>22s}")


def row_stat(nm, mk, show_flag=True):
    n = int(mk.sum())
    cn = gs_r(np.ones(NR), mk)
    a = ci_ratio(gs_r(err_min["A"], mk), cn); b = ci_ratio(gs_r(err_pts["A"], mk), cn)
    P(f"  {nm:44s} {n:7d} {f2(a):>22s} {f2(b):>22s}" + ("   (< 100 Zeilen)" if n < 100 else ""))


row_stat("ohne Ausfall (Kontrolle)", in_ctl_r)
row_stat("mit Ausfall (alle)", in_case_r)
for nm, mk in (("genau 1 Ausfall", n_abs == 1), ("genau 2 Ausfaelle", n_abs == 2), ("3 oder mehr Ausfaelle", n_abs >= 3), ("Top-3-Spieler fehlt", top3 == 1), ("nur Platz 4-8 fehlt", (top3 == 0) & (n_abs >= 1)),
               ("frisch Ausgefallener dabei", (fresh == 1) & (n_abs >= 1)), ("nur laenger Fehlende", (fresh == 0) & (n_abs >= 1))):
    row_stat("   " + nm, CASE[R["tgg"]] & mk[R["tgg"]])
P("  Differenz 'mit Ausfall' minus 'ohne Ausfall' (Veraenderung durch den Ausfall, in Minuten bzw. Punkten je Mitspieler), nach Rolle des Mitspielers:")
for ri, rn in enumerate(RNAME):
    mc, m0 = in_case_r & (ROLE == ri), in_ctl_r & (ROLE == ri)
    dm = ci_diff(gs_r(err_min["A"], mc), gs_r(np.ones(NR), mc), gs_r(err_min["A"], m0), gs_r(np.ones(NR), m0))
    dp = ci_diff(gs_r(err_pts["A"], mc), gs_r(np.ones(NR), mc), gs_r(err_pts["A"], m0), gs_r(np.ones(NR), m0))
    P(f"    {rn:20s} Zeilen mit Ausfall {int(mc.sum()):6d}: Minuten {f2(dm):>22s}  Punkte {f2(dp):>22s}" + ("   (< 100 Zeilen)" if mc.sum() < 100 else ""))
P("")

# Rueckfluss
P("2b RUECKFLUSS: Wie viel der prognostizierten Minuten/Punkte der Ausgefallenen fliesst an die Mitspieler?")
P("  Rueckfluss = (mittlere Summe der Mitspieler-Fehler je Team-Spiel mit Ausfall minus dasselbe ohne Ausfall) / mittlere Prognose des Ausgefallenen (rohe Prognose, Minuten bzw. Punkte). 100 % = alles fliesst zurueck.")
Fm, Fp = T["F_min"], T["F_pts"]


def flow(mask_tg, role=None, kind="min", model=None):
    """Rueckfluss-Anteil mit Intervall. model: None = Ist (Fehler gegen A), 'C' = was die Neuberechnung C gegenueber B verschiebt."""
    mr = np.ones(NR, bool) if role is None else (ROLE == role)
    if model is None:
        x = (err_min["A"] if kind == "min" else err_pts["A"])
        S = tg_sum(x, mr)
        n_case = gs_t(S, mask_tg); c_case = gs_t(np.ones(NTG), mask_tg)
        n_ctl = gs_t(S, CTL); c_ctl = gs_t(np.ones(NTG), CTL)
        F = gs_t(Fm if kind == "min" else Fp, mask_tg)
        pt = (n_case.sum() / c_case.sum() - n_ctl.sum() / c_ctl.sum()) / (F.sum() / c_case.sum())
        bs = ((W @ n_case) / (W @ c_case) - (W @ n_ctl) / (W @ c_ctl)) / ((W @ F) / (W @ c_case))
    else:
        x = (R["emin_C"] - R["emin_B"]) if kind == "min" else (R["epts_C"] - R["epts_B"])
        S = tg_sum(x, mr)
        n_case = gs_t(S, mask_tg); F = gs_t(Fm if kind == "min" else Fp, mask_tg)
        pt = n_case.sum() / F.sum()
        bs = (W @ n_case) / (W @ F)
    return float(pt), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def pc(t):
    return f"{100*t[0]:6.1f} % [{100*t[1]:.1f}; {100*t[2]:.1f}]"


P(f"  {'Gruppe (Team-Spiele)':34s} {'n':>5s} {'Ø Prognose Ausgefallene (Min / Pkt)':>36s} | {'Minuten: Ist':>24s} {'Minuten: Modell C-B':>24s} | {'Punkte: Ist':>24s} {'Punkte: Modell C-B':>24s}")
for nm, mk in (("alle mit Ausfall", CASE), ("genau 1 Ausfall", CASE & (n_abs == 1)), ("genau 2 Ausfaelle", CASE & (n_abs == 2)), ("3 oder mehr", CASE & (n_abs >= 3)), ("Top-3-Spieler fehlt", CASE & (top3 == 1)), ("nur Platz 4-8", CASE & (top3 == 0)),
               ("frisch Ausgefallener dabei", CASE & (fresh == 1)), ("nur laenger Fehlende", CASE & (fresh == 0))):
    n = int(mk.sum())
    P(f"  {nm:34s} {n:5d} {Fm[mk].mean():16.1f} / {Fp[mk].mean():5.1f}        | {pc(flow(mk)):>24s} {pc(flow(mk, model='C')):>24s} | {pc(flow(mk, kind='pts')):>24s} {pc(flow(mk, kind='pts', model='C')):>24s}" + ("   (< 100)" if mk.sum() < 100 else ""))
P("  ... und an wen (Anteil der prognostizierten Minuten/Punkte der Ausgefallenen, alle Fälle mit Ausfall):")
P(f"  {'Rolle der Mitspieler':26s} {'Minuten: Ist [95 %]':>26s} {'Minuten: Modell C-B':>26s} | {'Punkte: Ist [95 %]':>26s} {'Punkte: Modell C-B':>26s}")
for ri, rn in enumerate(RNAME):
    P(f"  {rn:26s} {pc(flow(CASE, role=ri)):>26s} {pc(flow(CASE, role=ri, model='C')):>26s} | {pc(flow(CASE, role=ri, kind='pts')):>26s} {pc(flow(CASE, role=ri, kind='pts', model='C')):>26s}")
P("")

# ------------------------------------------------------------------------------------------------ 3 Heutige Verteilung gegen Realitaet
KS = np.arange(1, 61)


def milestone_cells(Pm, rows_mask):
    """Summen (Brier) je Spiel fuer zwei Linienmengen: feste Meilensteine und Linien rund um den Spielerschnitt. Rueckgabe dict {set: (num_g, den_g)}."""
    idx = np.where(rows_mask)[0]
    pts = R["pts"][idx]
    out = {}
    # feste k
    se = np.zeros(len(idx))
    for k in FIXED_K:
        se += (Pm[idx, k - 1].astype(float) - (pts >= k)) ** 2
    out["fix"] = (np.bincount(R["gid"][idx], weights=se, minlength=G), np.bincount(R["gid"][idx], minlength=G).astype(float) * len(FIXED_K))
    nv = R["naive"][idx]
    ok = np.isfinite(nv)
    se2 = np.zeros(len(idx)); cnt = np.zeros(len(idx))
    for d in AROUND:
        k = np.clip(np.round(np.where(ok, nv, 10)).astype(int) + d, 1, 60)
        pk = Pm[idx, k - 1].astype(float)
        se2 += np.where(ok, (pk - (pts >= k)) ** 2, 0.0); cnt += ok
    out["avg"] = (np.bincount(R["gid"][idx], weights=se2, minlength=G), np.bincount(R["gid"][idx], weights=cnt, minlength=G))
    return out


def eval_block(title, mask_r, variants):
    """variants: dict name -> (emin, epts, Parr). Zeigt Minuten-/Punktefehler und Brier fuer die Zeilen mask_r."""
    n = int(mask_r.sum())
    P(f"  {title}  ({n} Spielerzeilen{', < 100: nicht aussagekraeftig' if n < 100 else ''})")
    P(f"    {'Variante':30s} {'Minuten Bias':>20s} {'Minuten MAE':>20s} {'Punkte Bias':>20s} {'Punkte MAE':>20s} {'Brier feste Meilensteine 10/15/20/25':>38s} {'Brier Linien um Schnitt':>26s}")
    cn = gs_r(np.ones(NR), mask_r)
    res = {}
    for nm, (em, ep, Pm) in variants.items():
        em_e, ep_e = R["min"] - em, R["pts"] - ep
        cells = milestone_cells(Pm, mask_r)
        res[nm] = {"cells": cells, "em_e": em_e, "ep_e": ep_e}
        P(f"    {nm:30s} {f2(ci_ratio(gs_r(em_e, mask_r), cn)):>20s} {f2u(ci_ratio(gs_r(np.abs(em_e), mask_r), cn)):>20s} {f2(ci_ratio(gs_r(ep_e, mask_r), cn)):>20s} {f2u(ci_ratio(gs_r(np.abs(ep_e), mask_r), cn)):>20s} "
          f"{f2u(ci_ratio(*cells['fix']), 4):>38s} {f2u(ci_ratio(*cells['avg']), 4):>26s}")
    return res, cn


def diff_line(res, cn, a, b, mask_r, label):
    """Variante a minus Variante b (negativ = a besser)."""
    ca, cb = res[a]["cells"], res[b]["cells"]
    bf = ci_diff(ca["fix"][0], ca["fix"][1], cb["fix"][0], cb["fix"][1])
    ba = ci_diff(ca["avg"][0], ca["avg"][1], cb["avg"][0], cb["avg"][1])
    mm = ci_diff(gs_r(np.abs(res[a]["em_e"]), mask_r), cn, gs_r(np.abs(res[b]["em_e"]), mask_r), cn)
    pm = ci_diff(gs_r(np.abs(res[a]["ep_e"]), mask_r), cn, gs_r(np.abs(res[b]["ep_e"]), mask_r), cn)
    P(f"    {label:22s} d Brier fest {f2((bf[0]*1000, bf[1]*1000, bf[2]*1000), 2)} x10^-3 | d Brier Schnitt {f2((ba[0]*1000, ba[1]*1000, ba[2]*1000), 2)} x10^-3 | d Minuten-MAE {f2(mm, 3)} | d Punkte-MAE {f2(pm, 3)}")
    return bf, ba, mm, pm


VAR3 = {"A roh": (R["emin_A"], R["epts_A"], PA), "B ohne Ausfaelle gerechnet": (R["emin_B"], R["epts_B"], PB), "C Neuberechnung mit Ausfaellen": (R["emin_C"], R["epts_C"], PC)}
P("3 HEUTIGE NEUBERECHNUNG GEGEN REALITAET (Spielerzeilen in Team-Spielen mit Ausfall)")
P("  Meilensteine: feste k = 10, 15, 20, 25 und die Linien rund um den Spielerschnitt (Saisonschnitt der Punkte vor dem Spiel, k = Runde(Schnitt) + {-2..+2}). Brier je (Spieler, k), Mittel; d = erste Variante minus zweite (negativ = erste besser).")
verdict3 = {}
for nm, mk_tg in (("alle Faelle mit Ausfall", CASE), ("Top-3-Spieler fehlt", CASE & (top3 == 1)), ("nur Platz 4-8 fehlt", CASE & (top3 == 0)), ("genau 1 Ausfall", CASE & (n_abs == 1)), ("3 oder mehr Ausfaelle", CASE & (n_abs >= 3)),
                  ("nur laenger Fehlende", CASE & (fresh == 0)), ("frisch Ausgefallener dabei", CASE & (fresh == 1))):
    mr = mk_tg[R["tgg"]]
    res, cn = eval_block(nm, mr, VAR3)
    verdict3[nm] = diff_line(res, cn, "C Neuberechnung mit Ausfaellen", "B ohne Ausfaelle gerechnet", mr, "C minus B")
    diff_line(res, cn, "C Neuberechnung mit Ausfaellen", "A roh", mr, "C minus A")
    P("")
mr_ctl = in_ctl_r
res0, cn0 = eval_block("Kontrolle: Team-Spiele ohne Ausfall (B = C)", mr_ctl, VAR3)
P("")

# ------------------------------------------------------------------------------------------------ 4 Datenbasierte Variante
P("4 DATENBASIERTE VERTEILUNG NACH ROLLE (Variante D)")
P("  D = rohe Prognose A + Rueckfluss nach Rolle: Minuten (bzw. Punkte) der Ausgefallenen x Anteil x_Rolle (y_Rolle) auf die Mitspieler der Rolle, innerhalb der Rolle proportional zu ihren erwarteten Minuten (Punkten).")
P("  Anteile x/y auf einer Haelfte der Daten bestimmt (Summe der Mitspieler-Fehler gegen A minus Kontrolle-Fehler je Zeile, geteilt durch die Prognose der Ausgefallenen), auf der anderen geprueft, und umgekehrt. Haelften = erste/zweite Saisonhaelfte beider Saisons.")


def learn(half):
    xs, ys = [], []
    for ri in range(3):
        m_ctl = in_ctl_r & (R["half"] == half) & (ROLE == ri)
        e0m, e0p = err_min["A"][m_ctl].mean(), err_pts["A"][m_ctl].mean()
        tgm = CASE & (tg_half == half)
        mr = (ROLE == ri) & tgm[R["tgg"]]
        n_r = np.bincount(R["tgg"][mr], minlength=NTG)
        Sm = tg_sum(err_min["A"], mr) - n_r * e0m
        Sp = tg_sum(err_pts["A"], mr) - n_r * e0p
        xs.append(Sm[tgm].sum() / Fm[tgm].sum()); ys.append(Sp[tgm].sum() / Fp[tgm].sum())
    return np.array(xs), np.array(ys)


FR = {h: learn(h) for h in (0, 1)}
for h in (0, 1):
    P(f"  Haelfte {h+1}: Minuten-Anteile Starter/Rotation/uebrige {FR[h][0][0]*100:.1f} / {FR[h][0][1]*100:.1f} / {FR[h][0][2]*100:.1f} % (Summe {FR[h][0].sum()*100:.1f} %); Punkte-Anteile {FR[h][1][0]*100:.1f} / {FR[h][1][1]*100:.1f} / {FR[h][1][2]*100:.1f} % (Summe {FR[h][1].sum()*100:.1f} %)")
# D-Prognose fuer die Zeilen der Pruefhaelfte
from backtest_player_markets import setup  # noqa: E402
from bt_player_adapter import Adapter, p_array  # noqa: E402

all_rows, flat, store, games, replay = setup()
adapter = Adapter(store)
D_emin = R["emin_A"].copy(); D_epts = R["epts_A"].copy(); PD = PA.copy()
cnt_fc = 0
for test_h, learn_h in ((1, 0), (0, 1)):
    x, y = FR[learn_h]
    tgm = CASE & (tg_half == test_h)
    mr = tgm[R["tgg"]]
    key = R["tgg"] * 3 + ROLE
    sum_min = np.bincount(key[mr], weights=R["emin_A"][mr], minlength=NTG * 3)
    sum_pts = np.bincount(key[mr], weights=R["epts_A"][mr], minlength=NTG * 3)
    for i in np.where(mr)[0]:
        tg = R["tgg"][i]; ri = ROLE[i]
        mn = R["emin_A"][i] + x[ri] * Fm[tg] * R["emin_A"][i] / max(sum_min[tg * 3 + ri], 1e-9)
        pt = R["epts_A"][i] + y[ri] * Fp[tg] * R["epts_A"][i] / max(sum_pts[tg * 3 + ri], 1e-9)
        mn = float(np.clip(mn, 0.0, 48.0)); pt = max(float(pt), 0.0)
        day = str(R["date"][i]); day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        is_home = bool(R["home"][i]); sp_home = R["spread"][i] if is_home else -R["spread"][i]
        f1 = adapter.forecast_player(int(R["pid"][i]), day, home=is_home, exp_spread=float(sp_home), minutes_mean_override=mn)
        s = pt / f1["expected_points"] if f1["expected_points"] > 1e-6 else 1.0
        f2_ = adapter.forecast_player(int(R["pid"][i]), day, home=is_home, exp_spread=float(sp_home), minutes_mean_override=mn, points_scale=float(np.clip(s, 0.3, 3.0)))
        D_emin[i], D_epts[i], PD[i] = f2_["minutes"]["mean"], f2_["expected_points"], p_array(f2_).astype(np.float32)
        cnt_fc += 1
P(f"  D-Prognosen gerechnet: {cnt_fc} Zeilen.")
P("")
VAR4 = {"A roh": (R["emin_A"], R["epts_A"], PA), "B ohne Ausfaelle gerechnet": (R["emin_B"], R["epts_B"], PB), "C Neuberechnung (heute)": (R["emin_C"], R["epts_C"], PC), "D Anteile nach Rolle": (D_emin, D_epts, PD)}
ok_both = []
for test_h, lbl in ((1, "bestimmt auf Haelfte 1, geprueft auf Haelfte 2"), (0, "bestimmt auf Haelfte 2, geprueft auf Haelfte 1")):
    tgm = CASE & (tg_half == test_h)
    mr = tgm[R["tgg"]]
    res, cn = eval_block(lbl, mr, VAR4)
    bf, ba, mm, pm = diff_line(res, cn, "D Anteile nach Rolle", "C Neuberechnung (heute)", mr, "D minus C")
    better = bf[0] < 0 and ba[0] < 0 and mm[0] < 0
    ok_both.append(better)
    P(f"    => D besser als C (Brier fest, Brier Schnitt und Minuten-MAE alle < 0): {'JA' if better else 'nein'}")
    P("")
P(f"  => Eine Variante zaehlt nur, wenn sie auf BEIDEN Pruefhaelften besser ist: D {'ZAEHLT' if all(ok_both) else 'zaehlt NICHT'}.")
P("")

# ------------------------------------------------------------------------------------------------ 5 Usage
P("5 USAGE: Punkte pro Minute der Mitspieler, wenn ein Stammspieler fehlt")
P("  Veraenderung = (Ist-Punkte - Prognose-ppm x Ist-Minuten) / Ist-Minuten, summiert ueber die Zeilen (minutengewichtet); Prognose-ppm = rohe Prognose-Punkte / Prognose-Minuten. Differenz = mit Ausfall minus ohne Ausfall (Kontrolle).")
ppm_fc = R["epts_A"] / np.maximum(R["emin_A"], 1e-9)
excess = R["pts"] - ppm_fc * R["min"]
P(f"  {'Gruppe':44s} {'Zeilen':>7s} {'ohne Ausfall: dppm [95 %]':>28s} {'mit Ausfall: dppm [95 %]':>28s} {'Differenz [95 %]':>26s}")


def usage_line(nm, mask_case_r, ri=None):
    mr_c = mask_case_r & (np.ones(NR, bool) if ri is None else ROLE == ri)
    mr_0 = in_ctl_r & (np.ones(NR, bool) if ri is None else ROLE == ri)
    a1 = ci_ratio(gs_r(excess, mr_c), gs_r(R["min"], mr_c)); a0 = ci_ratio(gs_r(excess, mr_0), gs_r(R["min"], mr_0))
    d = ci_diff(gs_r(excess, mr_c), gs_r(R["min"], mr_c), gs_r(excess, mr_0), gs_r(R["min"], mr_0))
    P(f"  {nm:44s} {int(mr_c.sum()):7d} {f2(a0, 4):>28s} {f2(a1, 4):>28s} {f2(d, 4):>26s}" + ("   (< 100 Zeilen)" if mr_c.sum() < 100 else ""))


for ri, rn in [(None, "alle Mitspieler")] + list(enumerate(RNAME)):
    usage_line(f"{rn}, Fall: irgendein Ausfall", in_case_r, ri)
for ri, rn in [(None, "alle Mitspieler")] + list(enumerate(RNAME)):
    usage_line(f"{rn}, Fall: Top-3-Spieler fehlt", (CASE & (top3 == 1))[R["tgg"]], ri)
for ri, rn in [(None, "alle Mitspieler")] + list(enumerate(RNAME)):
    usage_line(f"{rn}, Fall: nur Platz 4-8 fehlt", (CASE & (top3 == 0))[R["tgg"]], ri)
P(f"  (Mittlere Prognose-ppm der Mitspieler: {ppm_fc[in_case_r].mean():.3f}; 0,01 ppm entsprechen bei 30 Minuten 0,3 Punkten.)")
P("")

# ------------------------------------------------------------------------------------------------ Zusammenfassung
P("ZUSAMMENFASSUNG")
bf, ba, mm, pm = verdict3["alle Faelle mit Ausfall"]
P(f"  Faelle: {int(CASE.sum())} Team-Spiele mit Ausfall in {nspiele} Spielen ({int(in_case_r.sum())} Spielerzeilen) gegen {int(CTL.sum())} Kontroll-Team-Spiele.")
P(f"  Neuberechnung C gegen 'ohne Ausfaelle gerechnet' B in allen Faellen: d Brier fest {bf[0]*1000:+.2f} [{bf[1]*1000:+.2f}; {bf[2]*1000:+.2f}] x10^-3, d Brier Schnitt {ba[0]*1000:+.2f} [{ba[1]*1000:+.2f}; {ba[2]*1000:+.2f}], d Minuten-MAE {mm[0]:+.3f} [{mm[1]:+.3f}; {mm[2]:+.3f}].")
P(f"  Datenbasierte Variante D: {'besser auf beiden Haelften' if all(ok_both) else 'besteht die Zwei-Haelften-Regel nicht'}.")
P("  Hinweis: Obergrenze (Ausfaelle aus dem Boxscore); Zeilen eines Spiels/Spielers sind nicht unabhaengig, daher alle Intervalle nach Spielen.")
OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))

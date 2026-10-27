"""
Ausfall-Neuberechnung getrennt nach "neu fehlt" und "laenger fehlt". NUR LESEND, Produktivmodell unveraendert; schreibt nur analysis/reports/player_absence_new_vs_long.txt.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_absence_new_vs_long.py [--selftest]
Datenbasis: Zwischenstaende (npz) von analysis/backtest_player_absence.py (Replay, walk-forward, Adapter + Replay aus backtest_player_markets.py). Dort muss zuerst der Replay gelaufen sein.

Gruppen je Team-Spiel (Top 8 der laufenden Saison nach Minuten, ab dem 11. Teamspiel, Ausfall = 0 Minuten oder keine Zeile; Teamwechsel danach zaehlt nicht):
 neu    = mindestens ein Ausgefallener hat im vorigen Teamspiel noch gespielt (> 0 Minuten)
 laenger = alle Ausgefallenen haben auch im vorigen Teamspiel gefehlt
Varianten: A roh, B Teamabgleich ohne Ausfaelle, C heutige Neuberechnung, D = A + Rueckfluss nach Rolle (je Gruppe auf der einen Haelfte gelernt, auf der anderen geprueft),
 E = C in "neu"-Spielen, A in "laenger"-Spielen. Alle Intervalle: Bootstrap nach Spielen (beide Teams eines Spiels zusammen), 600 Ziehungen.
"""
import glob
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
_cands = sorted(glob.glob("/private/tmp/claude-501/-Users-baranalturk-Desktop-NBAEdge/*/scratchpad/pa"))
TMP = Path(_cands[0]) if _cands else None
OUT = HERE / "reports" / "player_absence_new_vs_long.txt"
SEASONS = ["2024-25", "2025-26"]
NB = 600
FIXED_K = [10, 15, 20, 25]
AROUND = [-2, -1, 0, 1, 2]
MINROWS = 100
L = []
P = L.append


def load_all():
    parts_r, parts_t, pa, pb, pc = [], [], [], [], []
    g_off = tg_off = 0
    for s in SEASONS:
        d = np.load(TMP / f"{s}.npz")
        r = {k[2:]: d[k] for k in d.files if k.startswith("r_")}
        t = {k[2:]: d[k] for k in d.files if k.startswith("t_")}
        r["gid"] = r["gi"] + g_off; r["tgg"] = r["tg"] + tg_off
        t["gid"] = t["gi"] + g_off; t["tgg"] = t["tg"] + tg_off
        g_off += int(d["n_games_total"][0]); tg_off += len(t["tg"])
        parts_r.append(r); parts_t.append(t); pa.append(d["pA"]); pb.append(d["pB"]); pc.append(d["pC"])
    R = {k: np.concatenate([p[k] for p in parts_r]) for k in parts_r[0]}
    T = {k: np.concatenate([p[k] for p in parts_t]) for k in parts_t[0]}
    return R, T, np.concatenate(pa), np.concatenate(pb), np.concatenate(pc), g_off, tg_off


def ci_ratio_f(W, num, den):
    if den.sum() == 0:
        return (np.nan,) * 3
    bs = (W @ num) / np.maximum(W @ den, 1e-12)
    return float(num.sum() / den.sum()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def ci_diff_f(W, n1, d1, n0, d0):
    if d1.sum() == 0 or d0.sum() == 0:
        return (np.nan,) * 3
    pt = n1.sum() / d1.sum() - n0.sum() / d0.sum()
    bs = (W @ n1) / np.maximum(W @ d1, 1e-12) - (W @ n0) / np.maximum(W @ d0, 1e-12)
    return float(pt), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def selftest():
    W = np.ones((5, 3))
    assert ci_ratio_f(W, np.array([2., 4., 6.]), np.array([1., 2., 3.]))[0] == 2.0
    o = np.ones(3)
    assert abs(ci_diff_f(W, 3 * o, o, o, o)[0] - 2.0) < 1e-12
    print("selftest ok")
    return 0


if "--selftest" in sys.argv:
    sys.exit(selftest())

R, T, PA, PB, PC, G, NTG = load_all()
NR = len(R["gid"])
_r = np.random.default_rng(7)
W = np.stack([np.bincount(_r.integers(0, G, G), minlength=G) for _ in range(NB)]).astype(float)
ci_ratio = lambda n, d: ci_ratio_f(W, n, d)            # noqa: E731
ci_diff = lambda a, b, c, d: ci_diff_f(W, a, b, c, d)  # noqa: E731


def gs_r(x, mask):
    return np.bincount(R["gid"][mask], weights=x[mask], minlength=G)


def gs_t(x, mask):
    return np.bincount(T["gid"][mask], weights=x[mask], minlength=G)


def f2(t, d=2):
    return "n/a" if not np.isfinite(t[0]) else f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]"


def f2u(t, d=2):
    return "n/a" if not np.isfinite(t[0]) else f"{t[0]:.{d}f} [{t[1]:.{d}f}; {t[2]:.{d}f}]"


def pc(t):
    return f"{100*t[0]:6.1f} % [{100*t[1]:.1f}; {100*t[2]:.1f}]"


n_abs, fresh = T["n_abs"], T["abs_fresh"]
rows_per_tg = np.bincount(R["tgg"], minlength=NTG)
valid_tg = rows_per_tg > 0
CTL = valid_tg & (n_abs == 0)
CASE = valid_tg & (n_abs >= 1)
NEU = CASE & (fresh == 1)
LANG = CASE & (fresh == 0)
tg_half = np.zeros(NTG, int)
tg_half[R["tgg"]] = R["half"]
ROLE = np.where(R["rank"] <= 5, 0, np.where(R["rank"] <= 9, 1, 2))
RNAME = ["Starter (Top 5)", "Rotation (6-9)", "uebrige (10+)"]
in_ctl_r = CTL[R["tgg"]]
neu_r, lang_r, case_r = NEU[R["tgg"]], LANG[R["tgg"]], CASE[R["tgg"]]
Fm, Fp = T["F_min"], T["F_pts"]
err_min = {X: R["min"] - R[f"emin_{X}"] for X in "ABC"}
err_pts = {X: R["pts"] - R[f"epts_{X}"] for X in "ABC"}


def tg_sum(x_r, mask_r):
    return np.bincount(R["tgg"][mask_r], weights=x_r[mask_r], minlength=NTG)


# ---------------------------------------------------------------------------------------------------- Kopf
P("AUSFAELLE: NEU FEHLENDE GEGEN LAENGER FEHLENDE SPIELER (Neuberechnung des Spielermodells, 2024-25 und 2025-26, walk-forward, echte Boxscores)")
P("Skript analysis/backtest_player_absence_new_vs_long.py (liest nur; Zwischenstaende des Replays aus analysis/backtest_player_absence.py; Produktivmodell unveraendert).")
P("ABGRENZUNG: Ausgefallen = Spieler der Top 8 des Teams nach Minuten der laufenden Saison bis zum Spieltag (ab dem 11. Teamspiel) mit 0 Minuten oder ohne Zeile im Spiel (Teamwechsel danach zaehlt nicht).")
P("  'neu fehlt' = der Spieler hat im vorigen Teamspiel noch gespielt (> 0 Minuten); 'laenger fehlt' = er hat auch im vorigen Teamspiel gefehlt.")
P("  Ein Team-Spiel zaehlt als 'neu', wenn mindestens ein neu fehlender Top-8-Spieler dabei ist (auch wenn zusaetzlich andere laenger fehlen), als 'nur laenger', wenn alle Ausfaelle laenger bestehen.")
P("VARIANTEN: A roh | B Teamabgleich ohne Ausfaelle | C heutige Neuberechnung (Teamabgleich mit Ausfaellen) | D = A + Rueckfluss nach Rolle (Anteile je Gruppe auf einer Haelfte gelernt, auf der anderen angewandt) | E = C nur in 'neu'-Spielen, in 'nur laenger'-Spielen A.")
P("ZEILEN: jede Spielerzeile der Mitspieler einzeln (nur Spieler mit Prognose UND Minuten > 0). Fehler = Ist minus Prognose. Intervalle 95 %: Bootstrap nach Spielen.")
P("OBERGRENZE: wer fehlte, ist aus dem Boxscore im Nachhinein bekannt. Im Betrieb ist nur Gemeldetes bekannt (spaete Ausfaelle fehlen, Fehlmeldungen kommen dazu), die Werte unten sind die bestmoegliche Lage fuer die Neuberechnung.")
P("")

# ---------------------------------------------------------------------------------------------------- 0 Faelle
P("0 FAELLE (Zahlen je Gruppe; Gruppen mit unter 100 Zeilen waeren nicht aussagekraeftig)")
P(f"  {'Gruppe':36s} {'Team-Spiele':>11s} {'Spiele':>7s} {'Spielerzeilen':>14s}")


def case_line(nm, mk):
    games = len(np.unique(T["gid"][mk]))
    rows = int(mk[R["tgg"]].sum())
    P(f"  {nm:36s} {int(mk.sum()):11d} {games:7d} {rows:14d}" + (f"   (< {MINROWS} Zeilen: nicht aussagekraeftig)" if rows < MINROWS else ""))


case_line("neu (mind. 1 neu fehlender)", NEU)
case_line("   davon Haelfte 1 (Saisonanfang)", NEU & (tg_half == 0))
case_line("   davon Haelfte 2 (Saisonende)", NEU & (tg_half == 1))
case_line("nur laenger", LANG)
case_line("   davon Haelfte 1", LANG & (tg_half == 0))
case_line("   davon Haelfte 2", LANG & (tg_half == 1))
case_line("alle Faelle mit Ausfall", CASE)
case_line("Kontrolle ohne Ausfall", CTL)
P("  (Ein Spiel hat zwei Team-Spiele; 'Spiele' zaehlt Spiele, in denen mindestens ein Team in der Gruppe liegt. Daher kann die Summe der Gruppen die Spielzahl uebersteigen.)")
P("")

# ---------------------------------------------------------------------------------------------------- 1 Rueckfluss
P("1 RUECKFLUSS: Wie viel der prognostizierten Minuten/Punkte der Ausgefallenen fliesst real an die Mitspieler?")
P("  Rueckfluss = (mittlere Summe der Mitspieler-Fehler gegen A je Team-Spiel der Gruppe minus dasselbe in der Kontrolle ohne Ausfall) / mittlere rohe Prognose der Ausgefallenen. 100 % = alles fliesst zurueck.")
P("  'Modell C-B' = wie viel die heutige Neuberechnung verschiebt (C minus B), im selben Verhaeltnis.")


def flow(mask_tg, role=None, kind="min", model=None):
    mr = np.ones(NR, bool) if role is None else (ROLE == role)
    if model is None:
        x = err_min["A"] if kind == "min" else err_pts["A"]
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


P(f"  {'Gruppe':22s} {'n':>5s} {'Ø Prognose Ausgef. (Min/Pkt)':>30s} | {'Minuten: real':>24s} {'Minuten: Modell C-B':>24s} | {'Punkte: real':>24s} {'Punkte: Modell C-B':>24s}")
FLOW = {}
for nm, mk in (("neu", NEU), ("nur laenger", LANG)):
    FLOW[nm] = {k: flow(mk, kind=k) for k in ("min", "pts")}
    n = int(mk.sum())
    P(f"  {nm:22s} {n:5d} {Fm[mk].mean():16.1f} / {Fp[mk].mean():5.1f}      | {pc(flow(mk)):>24s} {pc(flow(mk, model='C')):>24s} | {pc(flow(mk, kind='pts')):>24s} {pc(flow(mk, kind='pts', model='C')):>24s}" + ("   (< 100 Zeilen)" if mk[R['tgg']].sum() < MINROWS else ""))
P("  ... nach Rolle der Mitspieler (Anteil der prognostizierten Minuten/Punkte der Ausgefallenen):")
P(f"  {'Gruppe / Rolle':36s} {'Minuten: real':>24s} {'Minuten: Modell C-B':>24s} | {'Punkte: real':>24s} {'Punkte: Modell C-B':>24s}")
for nm, mk in (("neu", NEU), ("nur laenger", LANG)):
    for ri, rn in enumerate(RNAME):
        P(f"  {nm + ' / ' + rn:36s} {pc(flow(mk, role=ri)):>24s} {pc(flow(mk, role=ri, model='C')):>24s} | {pc(flow(mk, role=ri, kind='pts')):>24s} {pc(flow(mk, role=ri, kind='pts', model='C')):>24s}")
P("")

# ---------------------------------------------------------------------------------------------------- Brier
KS = np.arange(1, 61)


def milestone_cells(Pm, rows_mask):
    idx = np.where(rows_mask)[0]
    pts = R["pts"][idx]
    out = {}
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
    n = int(mask_r.sum())
    P(f"  {title}  ({n} Spielerzeilen{', < 100: nicht aussagekraeftig' if n < MINROWS else ''})")
    P(f"    {'Variante':26s} {'Minuten Bias':>20s} {'Minuten MAE':>20s} {'Punkte Bias':>20s} {'Punkte MAE':>20s} {'Brier feste 10/15/20/25':>26s} {'Brier Linien um Schnitt':>26s}")
    cn = gs_r(np.ones(NR), mask_r)
    res = {}
    for nm, (em, ep, Pm) in variants.items():
        em_e, ep_e = R["min"] - em, R["pts"] - ep
        cells = milestone_cells(Pm, mask_r)
        res[nm] = {"cells": cells, "em_e": em_e, "ep_e": ep_e}
        P(f"    {nm:26s} {f2(ci_ratio(gs_r(em_e, mask_r), cn)):>20s} {f2u(ci_ratio(gs_r(np.abs(em_e), mask_r), cn)):>20s} {f2(ci_ratio(gs_r(ep_e, mask_r), cn)):>20s} {f2u(ci_ratio(gs_r(np.abs(ep_e), mask_r), cn)):>20s} "
          f"{f2u(ci_ratio(*cells['fix']), 4):>26s} {f2u(ci_ratio(*cells['avg']), 4):>26s}")
    return res, cn


def diff_line(res, cn, a, b, mask_r, label):
    """a minus b (negativ = a besser). Rueckgabe (Brier fest, Brier Schnitt, Minuten-MAE, Punkte-MAE) je (Punkt, lo, hi)."""
    ca, cb = res[a]["cells"], res[b]["cells"]
    bf = ci_diff(ca["fix"][0], ca["fix"][1], cb["fix"][0], cb["fix"][1])
    ba = ci_diff(ca["avg"][0], ca["avg"][1], cb["avg"][0], cb["avg"][1])
    mm = ci_diff(gs_r(np.abs(res[a]["em_e"]), mask_r), cn, gs_r(np.abs(res[b]["em_e"]), mask_r), cn)
    pm = ci_diff(gs_r(np.abs(res[a]["ep_e"]), mask_r), cn, gs_r(np.abs(res[b]["ep_e"]), mask_r), cn)
    P(f"    {label:20s} d Brier fest {f2((bf[0]*1000, bf[1]*1000, bf[2]*1000), 2)} x10^-3 | d Brier Schnitt {f2((ba[0]*1000, ba[1]*1000, ba[2]*1000), 2)} x10^-3 | d Minuten-MAE {f2(mm, 3)} | d Punkte-MAE {f2(pm, 3)}")
    return bf, ba, mm, pm


def flag(t):
    return "besser" if t[2] < 0 else ("schlechter" if t[1] > 0 else "unklar")


# ---------------------------------------------------------------------------------------------------- D bauen
def learn(half, gmask_tg):
    xs, ys = [], []
    for ri in range(3):
        m_ctl = in_ctl_r & (R["half"] == half) & (ROLE == ri)
        e0m, e0p = err_min["A"][m_ctl].mean(), err_pts["A"][m_ctl].mean()
        tgm = gmask_tg & (tg_half == half)
        mr = (ROLE == ri) & tgm[R["tgg"]]
        n_r = np.bincount(R["tgg"][mr], minlength=NTG)
        Sm = tg_sum(err_min["A"], mr) - n_r * e0m
        Sp = tg_sum(err_pts["A"], mr) - n_r * e0p
        xs.append(Sm[tgm].sum() / Fm[tgm].sum()); ys.append(Sp[tgm].sum() / Fp[tgm].sum())
    return np.array(xs), np.array(ys)


from backtest_player_markets import setup  # noqa: E402
from bt_player_adapter import Adapter, p_array  # noqa: E402

all_rows, flat, store, games, replay = setup()
adapter = Adapter(store)
D_emin = R["emin_A"].copy(); D_epts = R["epts_A"].copy(); PD = PA.copy()
SHARES = {}
for gname, gmask in (("neu", NEU), ("laenger", LANG)):
    for learn_h in (0, 1):
        SHARES[(gname, learn_h)] = learn(learn_h, gmask)
cnt_fc = 0
for gname, gmask in (("neu", NEU), ("laenger", LANG)):
    for test_h, learn_h in ((1, 0), (0, 1)):
        x, y = SHARES[(gname, learn_h)]
        tgm = gmask & (tg_half == test_h)
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

# E = C bei 'neu', sonst A
E_emin = np.where(neu_r, R["emin_C"], R["emin_A"]); E_epts = np.where(neu_r, R["epts_C"], R["epts_A"]); PE = np.where(neu_r[:, None], PC, PA)

P("2 GELERNTE ANTEILE VON D (je Gruppe, je Haelfte; Rueckfluss nach Rolle: Starter / Rotation / uebrige)")
for (gname, h), (x, y) in sorted(SHARES.items()):
    P(f"  {gname:8s} Haelfte {h+1}: Minuten {x[0]*100:.1f} / {x[1]*100:.1f} / {x[2]*100:.1f} % (Summe {x.sum()*100:.1f} %); Punkte {y[0]*100:.1f} / {y[1]*100:.1f} / {y[2]*100:.1f} % (Summe {y.sum()*100:.1f} %)")
P(f"  D-Prognosen gerechnet: {cnt_fc} Zeilen (jede Zeile nur mit Anteilen der jeweils anderen Haelfte).")
P("")

# ---------------------------------------------------------------------------------------------------- 3 Vergleich je Gruppe
VAR = {"A roh": (R["emin_A"], R["epts_A"], PA), "B ohne Ausfaelle gerechnet": (R["emin_B"], R["epts_B"], PB), "C Neuberechnung (heute)": (R["emin_C"], R["epts_C"], PC), "D Anteile nach Rolle": (D_emin, D_epts, PD)}
P("3 VERGLEICH A / B / C / D JE GRUPPE (alle Spielerzeilen der Gruppe; d = Variante minus A, negativ = besser als A; Brier-Einheit x10^-3)")
G3 = {}
for nm, mk_tg in (("NEU FEHLT", NEU), ("NUR LAENGER FEHLT", LANG)):
    mr = mk_tg[R["tgg"]]
    res, cn = eval_block(nm, mr, VAR)
    G3[nm] = {v: diff_line(res, cn, v, "A roh", mr, v.split()[0] + " minus A") for v in ("B ohne Ausfaelle gerechnet", "C Neuberechnung (heute)", "D Anteile nach Rolle")}
    P("")


def verdict_line(gname, key, tag):
    d = G3[gname][key]
    parts = [f"Brier fest {flag(d[0])}", f"Brier Schnitt {flag(d[1])}", f"Minuten-MAE {flag(d[2])}", f"Punkte-MAE {flag(d[3])}"]
    P(f"    {tag} gegen A in '{gname.lower()}': " + ", ".join(parts))


P("  Antwort auf die Frage (Intervall des Unterschieds zu A ganz unter 0 = besser, ganz ueber 0 = schlechter, sonst unklar):")
for key, tag in (("C Neuberechnung (heute)", "C"), ("D Anteile nach Rolle", "D")):
    for gname in ("NEU FEHLT", "NUR LAENGER FEHLT"):
        verdict_line(gname, key, tag)
P("")

# ---------------------------------------------------------------------------------------------------- 4 Zwei-Haelften neu
P("4 ZWEI-HAELFTEN-REGEL NUR FUER 'NEU' (C hat keinen freien Parameter und wird unveraendert auf beiden Haelften geprueft; D: Anteile aus der jeweils anderen Haelfte)")
P("  Eine Variante zaehlt nur, wenn sie auf BEIDEN Pruefhaelften besser als A ist (Punktschaetzer von Brier fest, Brier Schnitt und Minuten-MAE alle < 0). Zusaetzlich 'sicher' = Intervall des Unterschieds in allen drei ganz unter 0.")
ok2 = {"C": [], "D": []}
sure2 = {"C": [], "D": []}
for test_h, lbl in ((1, "Pruefhaelfte 2 (D gelernt auf Haelfte 1)"), (0, "Pruefhaelfte 1 (D gelernt auf Haelfte 2)")):
    mr = (NEU & (tg_half == test_h))[R["tgg"]]
    res, cn = eval_block("neu, " + lbl, mr, VAR)
    for v, key in (("C", "C Neuberechnung (heute)"), ("D", "D Anteile nach Rolle")):
        bf, ba, mm, pm = diff_line(res, cn, key, "A roh", mr, f"{v} minus A")
        ok2[v].append(bf[0] < 0 and ba[0] < 0 and mm[0] < 0)
        sure2[v].append(bf[2] < 0 and ba[2] < 0 and mm[2] < 0)
    P("")
for v in ("C", "D"):
    P(f"  => {v} in 'neu': besser als A auf beiden Pruefhaelften (Punktschaetzer): {'JA' if all(ok2[v]) else 'NEIN'}; mit Intervall ganz unter 0 auf beiden: {'JA' if all(sure2[v]) else 'NEIN'}  -> {v} {'zaehlt' if all(ok2[v]) else 'zaehlt NICHT'}")
P("")

# ---------------------------------------------------------------------------------------------------- 5 Regel E
P("5 REGEL-TEST E: Neuberechnung nur fuer neu fehlende Spieler (C), fuer laenger fehlende die rohe Prognose (A). Alle Faelle mit Ausfall.")
VARE = {"A roh": (R["emin_A"], R["epts_A"], PA), "C Neuberechnung (heute)": (R["emin_C"], R["epts_C"], PC), "E nur neu neu berechnet": (E_emin, E_epts, PE)}
ok5 = {"A": [], "C": []}
sure5 = {"A": [], "C": []}
res, cn = eval_block("alle Faelle mit Ausfall (beide Haelften)", case_r, VARE)
diff_line(res, cn, "E nur neu neu berechnet", "A roh", case_r, "E minus A")
diff_line(res, cn, "E nur neu neu berechnet", "C Neuberechnung (heute)", case_r, "E minus C")
P("")
for test_h, lbl in ((1, "Pruefhaelfte 2"), (0, "Pruefhaelfte 1")):
    mr = (CASE & (tg_half == test_h))[R["tgg"]]
    res, cn = eval_block("alle Faelle mit Ausfall, " + lbl, mr, VARE)
    for ref, key in (("A", "A roh"), ("C", "C Neuberechnung (heute)")):
        bf, ba, mm, pm = diff_line(res, cn, "E nur neu neu berechnet", key, mr, f"E minus {ref}")
        ok5[ref].append(bf[0] < 0 and ba[0] < 0 and mm[0] < 0)
        sure5[ref].append(bf[2] < 0 and ba[2] < 0 and mm[2] < 0)
    P("")
for ref in ("A", "C"):
    P(f"  => E besser als {ref} auf beiden Pruefhaelften (Punktschaetzer Brier fest, Brier Schnitt, Minuten-MAE): {'JA' if all(ok5[ref]) else 'NEIN'}; mit Intervall ganz unter 0 auf beiden: {'JA' if all(sure5[ref]) else 'NEIN'}")
P("  (E hat keinen freien Parameter; die Regel 'neu = Neuberechnung' ist vorab festgelegt, also ist die Haelftenpruefung eine Stabilitaetskontrolle.)")
P("")

# ---------------------------------------------------------------------------------------------------- Zusammenfassung
P("ZUSAMMENFASSUNG")
for gname, mk in (("NEU FEHLT", NEU), ("NUR LAENGER FEHLT", LANG)):
    P(f"  {gname}: {int(mk.sum())} Team-Spiele in {len(np.unique(T['gid'][mk]))} Spielen, {int(mk[R['tgg']].sum())} Spielerzeilen.")
P(f"  Rueckfluss real (Minuten): neu {pc(FLOW['neu']['min'])}, nur laenger {pc(FLOW['nur laenger']['min'])}; Punkte: neu {pc(FLOW['neu']['pts'])}, nur laenger {pc(FLOW['nur laenger']['pts'])}.")
P(f"  Zwei-Haelften-Regel 'neu': C {'zaehlt' if all(ok2['C']) else 'zaehlt nicht'}, D {'zaehlt' if all(ok2['D']) else 'zaehlt nicht'}; E gegen A {'besser' if all(ok5['A']) else 'nicht auf beiden Haelften besser'}, E gegen C {'besser' if all(ok5['C']) else 'nicht auf beiden Haelften besser'}.")
P("  Hinweis: Obergrenze (Ausfaelle aus dem Boxscore im Nachhinein bekannt); Zeilen eines Spiels/Spielers sind nicht unabhaengig, daher Intervalle nach Spielen.")
OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))

"""
Modell-Tuning, Schritt 2: Parametervergleich gegen die Baseline (analysis/tuning_baseline.py). Nur lesend: liest data/cache und das Pickle (nur Pruefung),
schreibt nur analysis/results/tuning_grid.json. Keine API-Calls. Produktivdateien und old_engine_replica.py bleiben unveraendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/tuning_grid.py

Aufbau
1. Nachbau analysis/replica_tunable.py (Parameter: carry/keep, hca, MOV-Faktor oder 538-Variante, K, Total-Carry). Standardwerte = Produktivwerte; vorab geprueft.
2. Gitter bewusst klein: carry 1,0/0,8/0,7/0,6/0,5/0,4 (Anteil der Ratings, der den Sommer ueberlebt), hca 100/90/80/70, MOV-Faktor 2,2/1,8/1,4/1,0 und 538-Variante,
   K 20/16/14/12 NUR zusammen mit MOV-Daempfung (Faktor < 2,2 oder 538). Erst jede Achse einzeln (Rest = Produktivwerte), dann Kombinationen.
3. Strikte Trennung: Fuer Test-Saison S wird NUR aus den Saisons 2017 bis S-1 gewaehlt (Walk-forward; Kriterium Brier, je 50 % erste 20 Spiele / 50 % alle Spiele).
   Die gewaehlten Varianten werden dann auf S bewertet ("Walk-forward-Auswahl", zusammengesetzt ueber S). Die Einzelachsen-Tabellen mit festen Werten sind eine
   BESCHREIBUNG des vorab festgelegten Gitters und gehen nicht in die Auswahl ein.
4. Differenz zur Baseline je Markt (Sieger, Spread, Total, Team Total Heim/Gast) mit paired Bootstrap (2000 Ziehungen, 95 %).
   Gewinn-Regel: Intervall der Brier- ODER Spread-MAE-Differenz schliesst 0 NICHT ein (Verbesserung) in BEIDEN Hauptfenstern (a: erste 20 Spiele, b: alle Spiele 2023-25)
   UND die Kontrollfenster 2021/22 (c1, c2) werden bei Brier und Spread-MAE nicht schlechter (Punktschaetzung der Differenz <= 0).
5. Total: Saisonstart-Bias je Saison und Wirkung der Sommer-Regression der Off/Def-Werte (total_keep).
Skala: Die produktive Spread-Skala ist fest (ELO-Differenz / 50). Aendert eine Variante die Breite der Ratings (MOV-Daempfung, K, carry), passt der feste Faktor nicht mehr
(die Siegwahrscheinlichkeit nicht betroffen: die Logistik wird je Variante neu trainiert). Deshalb wird Spread/Team Total in ZWEI Modi ausgewiesen:
"Skala fest" (Faktor 50 wie produktiv) und "Skala neu" (Steigung Marge ~ ELO-Differenz je Test-Saison nur aus frueheren Saisons neu bestimmt, durch den Ursprung,
damit der Heimvorteil-Parameter wirksam bleibt). Referenz bleibt in beiden Modi die produktive Baseline (Faktor 50).
Team Total: Prognose Heim = (Total + Spread) / 2, Gast = (Total - Spread) / 2 (wie engine/projection.py); Kalibrierung mit der produktiven Sigma 12,5
(engine/line_probabilities.TEAM_TOTAL_SIGMA) auf Test-Linien Prognose(gerundet) + {-12 ... +12} + 0,5; es gibt keine historischen Buchmacherlinien.
"""
import hashlib
import itertools
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import ROOT, RESULTS, load_games, window, logloss, phi  # noqa: E402
import old_engine_replica as old  # noqa: E402
import replica_tunable as rt  # noqa: E402
import tuning_baseline as tb  # noqa: E402

N_BOOT = tb.N_BOOT
WINDOWS = tb.WINDOWS                       # a, b, c1, c2
WNAMES = [w[0] for w in WINDOWS]
INNER_FIRST = 2017
PROB_SEASONS = list(range(INNER_FIRST, 2026))
TEST_SEASONS = [2021, 2022, 2023, 2024, 2025]
SIG_TT = 12.5
TT_OFFSETS = np.array([-12, -9, -6, -3, 0, 3, 6, 9, 12]) + 0.5
CARRY = [1.0, 0.8, 0.7, 0.6, 0.5, 0.4]
HCA = [100.0, 90.0, 80.0, 70.0]
MOVK = ([dict(mov="cur", mov_factor=2.2, K=20.0)]
        + [dict(mov="cur", mov_factor=f, K=20.0) for f in (1.8, 1.4, 1.0)]
        + [dict(mov="cur", mov_factor=f, K=k) for f in (1.8, 1.4, 1.0) for k in (16.0, 14.0, 12.0)]
        + [dict(mov="538", mov_factor=2.2, K=k) for k in (20.0, 16.0, 14.0, 12.0)])
TOTAL_KEEP = [1.0, 0.8, 0.6, 0.4, 0.2]
BASE = dict(K=20.0, hca=100.0, mov="cur", mov_factor=2.2, keep=1.0, total_keep=1.0)

# (Schluessel, Markt, Name, Einheit/Faktor fuer die Anzeige, mehr = besser?)
METRICS = [("s_hit", "Sieger", "Trefferquote", 100.0), ("s_brier", "Sieger", "Brier", 1000.0), ("s_ll", "Sieger", "Log-Loss", 1000.0),
           ("sp_mae", "Spread", "MAE", 1.0), ("sp_bias", "Spread", "Bias", 1.0), ("sp_hit", "Spread", "Seite richtig", 100.0),
           ("t_mae", "Total", "MAE", 1.0), ("t_bias", "Total", "Bias", 1.0),
           ("th_mae", "Team Total Heim", "MAE", 1.0), ("th_bias", "Team Total Heim", "Bias", 1.0), ("th_cal", "Team Total Heim", "Kalib.(Brier O/U)", 1000.0),
           ("ta_mae", "Team Total Gast", "MAE", 1.0), ("ta_bias", "Team Total Gast", "Bias", 1.0), ("ta_cal", "Team Total Gast", "Kalib.(Brier O/U)", 1000.0)]
MKEYS = [m[0] for m in METRICS]
MIDX = {k: i for i, k in enumerate(MKEYS)}


def sha(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def cfg(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


def ckey(c):
    return json.dumps(c, sort_keys=True)


def label(c):
    parts = []
    if c["keep"] != 1.0:
        parts.append(f"carry {c['keep']:g}")
    if c["hca"] != 100.0:
        parts.append(f"hca {c['hca']:g}")
    if c["mov"] == "538":
        parts.append(f"538 K{c['K']:g}")
    else:
        if c["mov_factor"] != 2.2:
            parts.append(f"MOV {c['mov_factor']:g}")
        if c["K"] != 20.0:
            parts.append(f"K {c['K']:g}")
    if c["total_keep"] != 1.0:
        parts.append(f"Total-carry {c['total_keep']:g}")
    return " + ".join(parts) or "Baseline"


# --------------------------------------------------------------------------- #
#  Lauf einer Konfiguration                                                     #
# --------------------------------------------------------------------------- #
class Runner:
    def __init__(self, games):
        self.games, self.cache = games, {}
        self.t_run = self.t_prob = 0.0
        self.n_runs = 0

    def get(self, c):
        k = ckey(c)
        if k not in self.cache:
            t0 = time.perf_counter()
            arr, _se, _off, _de = rt.run(self.games, K=c["K"], hca=c["hca"], mov=c["mov"], mov_factor=c["mov_factor"], keep=c["keep"], total_keep=c["total_keep"])
            t1 = time.perf_counter()
            p = tb.walk_forward_probs(arr, PROB_SEASONS)
            t2 = time.perf_counter()
            self.t_run += t1 - t0
            self.t_prob += t2 - t1
            self.n_runs += 1
            d, mg, season, reg = arr["diff"], arr["margin"], arr["season"], arr["post"] == 0
            sp_r = d / tb.SPREAD_FACTOR
            for S in PROB_SEASONS:                              # Skala je Saison nur aus frueheren Saisons (Regular Season), Regression durch den Ursprung
                tr = (season < S) & reg
                sp_r[season == S] = d[season == S] * float((d[tr] * mg[tr]).sum() / (d[tr] ** 2).sum())
            self.cache[k] = {"p": np.nan_to_num(p, nan=0.5), "sp": d / tb.SPREAD_FACTOR, "sp_r": sp_r, "tp": arr["total_pred"], "arr": arr}
        return self.cache[k]


def tt_cal(pred, actual):
    """Brier-Wert der Ueber/Unter-Wahrscheinlichkeit auf den Test-Linien (je Spiel Mittel ueber die Linien) plus (p, Ergebnis) fuer die Klassentabelle."""
    mean = np.round(pred)
    lines = mean[:, None] + TT_OFFSETS[None, :]
    p_over = 1.0 - phi((lines - mean[:, None]) / SIG_TT)
    over = (actual[:, None] > lines).astype(float)
    return ((p_over - over) ** 2).mean(axis=1), p_over, over


def per_game(V, base):
    """Matrix (Spiele x Kennzahlen) der Einzelwerte einer Variante; Mittelwerte ergeben die Kennzahl."""
    arr = base["arr"]
    y, margin, total = arr["hw"], arr["margin"], arr["total"]
    p, sp, tp = V["p"], V["sp"], V["tp"]
    home_pred, away_pred = (tp + sp) / 2, (tp - sp) / 2
    home_act, away_act = (total + margin) / 2, (total - margin) / 2
    eh, ea = home_pred - home_act, away_pred - away_act
    cols = {"s_hit": ((p > 0.5) == (y > 0.5)).astype(float), "s_brier": (p - y) ** 2, "s_ll": logloss(p, y),
            "sp_mae": np.abs(sp - margin), "sp_bias": sp - margin, "sp_hit": ((sp > 0) == (margin > 0)).astype(float),
            "t_mae": np.abs(tp - total), "t_bias": tp - total,
            "th_mae": np.abs(eh), "th_bias": eh, "th_cal": tt_cal(home_pred, home_act)[0],
            "ta_mae": np.abs(ea), "ta_bias": ea, "ta_cal": tt_cal(away_pred, away_act)[0]}
    return np.column_stack([cols[k] for k in MKEYS])


class Boot:
    """Gemeinsame Ziehungen je Fenster: Mittelwerte per Matrixprodukt (Zaehlmatrix x Einzelwerte)."""
    def __init__(self, masks, seed=0):
        self.masks, self.C = masks, {}
        for name, m in masks.items():
            n = int(m.sum())
            rng = np.random.default_rng(seed)
            idx = rng.integers(0, n, (N_BOOT, n))
            self.C[name] = np.stack([np.bincount(r, minlength=n) for r in idx]).astype(np.float64)

    def diff(self, name, Dv, Db):
        """Mittlere Differenz Variante - Baseline je Kennzahl mit 95-%-Intervall: (n_metrics x 3)."""
        m = self.masks[name]
        d = Dv[m] - Db[m]
        n = d.shape[0]
        boots = self.C[name] @ d / n
        return np.column_stack([d.mean(axis=0), np.percentile(boots, 2.5, axis=0), np.percentile(boots, 97.5, axis=0)])


def evaluate(V, base, Dbase, boot, recal=False):
    if recal:
        V = {**V, "sp": V["sp_r"]}
    Dv = per_game(V, base)
    out = {}
    for name in WNAMES:
        m = boot.masks[name]
        res = boot.diff(name, Dv, Dbase)
        absval = Dv[m].mean(axis=0)
        out[name] = {k: [float(res[i, 0]), float(res[i, 1]), float(res[i, 2]), float(absval[i])] for i, k in enumerate(MKEYS)}
    return out


def verdict(ev):
    """Gewinn-Regel (siehe Kopf). Rueckgabe (Gewinn?, Begruendung)."""
    def better(w):
        r = ev[w]
        return r["s_brier"][2] < 0 or r["sp_mae"][2] < 0                    # oberes Intervallende < 0 = Verbesserung belegt
    main_ok = better("a_erste20_2023-25") and better("b_alle_2023-25")
    ctrl_ok = all(ev[w]["s_brier"][0] <= 0 and ev[w]["sp_mae"][0] <= 0 for w in ("c1_kontrolle_erste20_2021-22", "c2_kontrolle_alle_2021-22"))
    why = []
    why.append("a" + ("+" if better("a_erste20_2023-25") else "-"))
    why.append("b" + ("+" if better("b_alle_2023-25") else "-"))
    why.append("Kontrolle " + ("ok" if ctrl_ok else "schlechter"))
    return bool(main_ok and ctrl_ok), " ".join(why)


# --------------------------------------------------------------------------- #
#  Walk-forward-Auswahl                                                         #
# --------------------------------------------------------------------------- #
def inner_score(V, base, folds):
    arr = base["arr"]
    err = (V["p"] - arr["hw"]) ** 2
    m = np.isin(arr["season"], folds) & (arr["post"] == 0)
    e = m & (arr["gp_h"] < 20) & (arr["gp_a"] < 20)
    return 0.5 * err[e].mean() + 0.5 * err[m].mean()


def stitch(chosen, runner, base):
    """Zusammengesetzte Vorhersagen: je Test-Saison S die Werte der fuer S gewaehlten Konfiguration (Auswahl nur aus Saisons < S)."""
    p, sp, sp_r, tp = base["p"].copy(), base["sp"].copy(), base["sp_r"].copy(), base["tp"].copy()
    season = base["arr"]["season"]
    for S, c in chosen.items():
        V, m = runner.get(c), season == S
        p[m], sp[m], sp_r[m], tp[m] = V["p"][m], V["sp"][m], V["sp_r"][m], V["tp"][m]
    return {"p": p, "sp": sp, "sp_r": sp_r, "tp": tp}


# --------------------------------------------------------------------------- #
#  Ausgabe                                                                      #
# --------------------------------------------------------------------------- #
def cell(r, factor, signed=True):
    d, lo, hi = r[0] * factor, r[1] * factor, r[2] * factor
    star = "*" if (lo > 0 or hi < 0) else " "
    return f"{d:+8.2f}{star}"


SHOW = [("a_erste20_2023-25", "a"), ("b_alle_2023-25", "b"), ("c2_kontrolle_alle_2021-22", "c")]


def market_table(title, mkeys, rows, write):
    """rows: [(Bezeichnung, ev-Dict, Gewinn-Text oder None)]. Je Kennzahl drei Fenster: a = erste 20 Spiele 2023-25, b = alle 2023-25, c = Kontrolle alle 2021/22."""
    heads = [next(m for m in METRICS if m[0] == k) for k in mkeys]
    write(f"\n--- {title} ---  (Differenz Variante - Baseline; * = 95-%-Intervall schliesst 0 nicht ein)")
    unit = {1.0: "Punkte", 100.0: "Prozentpunkte", 1000.0: "x 10^-3"}
    write("  Einheiten: " + ", ".join(f"{h[2]} [{unit[h[3]]}]" for h in heads) + "; Fenster je Kennzahl: a | b | c")
    line = f"  {'Variante':<34}" + "".join(f"{h[2][:14]:^27}" for h in heads)
    write(line)
    for lab, ev, extra in rows:
        s = f"  {lab[:34]:<34}"
        for k, h in zip(mkeys, heads):
            s += "".join(cell(ev[w][k], h[3]) for w, _ in SHOW)
        write(s + (f"  {extra}" if extra else ""))


def calib_table(pred, actual, mask, write, title):
    _b, p_over, over = tt_cal(pred[mask], actual[mask])
    p, o = p_over.ravel(), over.ravel()
    write(f"  {title}")
    write(f"    {'Klasse':<11}{'n':>7}{'mittleres p(Ueber)':>20}{'tatsaechlich Ueber':>20}{'Diff.':>8}")
    edges = np.linspace(0, 1, 11)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & ((p < hi) if hi < 1 else (p <= hi))
        if m.sum():
            write(f"    {lo:.1f}-{hi:.1f}  {int(m.sum()):>7}{p[m].mean():>20.3f}{o[m].mean():>20.3f}{o[m].mean() - p[m].mean():>+8.3f}")
            out.append({"von": round(float(lo), 1), "bis": round(float(hi), 1), "n": int(m.sum()), "p": float(p[m].mean()), "tatsaechlich": float(o[m].mean())})
    return out


def rnd(x, d=5):
    return round(float(x), d)


def main(write=print):
    T0 = time.perf_counter()
    files = [ROOT / "data" / "elo_model.pkl", ROOT / "models" / "elo.py", ROOT / "config" / "settings.py", ROOT / "analysis" / "old_engine_replica.py"]
    sha_before = {f.name: sha(f) for f in files}
    games = load_games()
    runner = Runner(games)

    # ---- Vorpruefung: Nachbau == Baseline-Nachbau == Pickle
    o_old, _se = old.run(games, **tb.PRODUCTION)
    base = runner.get(cfg())
    same = all(np.allclose(base["arr"][k], o_old[k], atol=1e-9) for k in ("season", "post", "gp_h", "gp_a", "diff", "fdiff", "rdiff", "margin", "hw", "total"))
    tp_ref, off, de = tb.total_predictions(games)
    arr0, se0, off0, de0 = rt.run(games)
    chk = tb.check_against_pickle(games, se0, off0, de0)
    ok = same and np.allclose(base["tp"], tp_ref, atol=1e-9) and chk["ok"]
    write(f"Vorpruefung: replica_tunable (Produktivwerte) == old_engine_replica: {same}; Total == Engine-Regel: {bool(np.allclose(base['tp'], tp_ref, atol=1e-9))}; "
          f"== Pickle (24 Teams exakt, 6 Teams mit neueren Spielen): {chk['ok']}")
    if not ok:
        write("ABBRUCH: Der Nachbau passt nicht zur Produktivengine.")
        return 2

    arr = base["arr"]
    masks = {}
    for name, ss, early in WINDOWS:
        m = np.zeros(len(arr["season"]), bool)
        for S in ss:
            m |= window(arr, S, early)
        masks[name] = m
    boot = Boot(masks)
    Dbase = per_game(base, base)

    # ---- Einzelachsen (feste Werte, Beschreibung)
    axes = {"carry": [cfg(keep=k) for k in CARRY], "hca": [cfg(hca=h) for h in HCA], "movk": [cfg(**m) for m in MOVK]}
    results, results_r = {}, {}
    for ax, lst in axes.items():
        for c in lst:
            if ckey(c) == ckey(cfg()):
                continue
            results[ckey(c)] = evaluate(runner.get(c), base, Dbase, boot)
            results_r[ckey(c)] = evaluate(runner.get(c), base, Dbase, boot, recal=True)
    results_r[ckey(cfg())] = evaluate(base, base, Dbase, boot, recal=True)       # Kontrolle: Baseline mit neu angepasster Skala
    t_axes = time.perf_counter()

    # ---- Walk-forward-Auswahl je Test-Saison
    chosen_axis = {ax: {} for ax in axes}
    chosen_combo = {r: {} for r in range(5)}
    top_log = {}
    for S in TEST_SEASONS:
        folds = list(range(INNER_FIRST, S))
        tops = {}
        for ax, lst in axes.items():
            sc = sorted(((inner_score(runner.get(c), base, folds), ckey(c), c) for c in lst), key=lambda x: (x[0], x[1]))
            chosen_axis[ax][S] = sc[0][2]
            tops[ax] = [x[2] for x in sc[:2]]
        combos = {}
        for a_, b_, c_ in itertools.product(tops["carry"], tops["hca"], tops["movk"]):
            c = cfg(keep=a_["keep"], hca=b_["hca"], mov=c_["mov"], mov_factor=c_["mov_factor"], K=c_["K"])
            combos[ckey(c)] = c
        ranked = sorted(((inner_score(runner.get(c), base, folds), k, c) for k, c in combos.items()), key=lambda x: (x[0], x[1]))[:5]
        for r, (s_, _k, c) in enumerate(ranked):
            chosen_combo[r][S] = c
        top_log[S] = {"achsen": {ax: label(chosen_axis[ax][S]) for ax in axes}, "kombinationen": [(label(c), rnd(s_, 5)) for s_, _k, c in ranked],
                      "inner_score_baseline": rnd(inner_score(base, base, folds), 5)}
    t_sel = time.perf_counter()
    nested, nested_r = {}, {}
    for ax in axes:
        st = stitch(chosen_axis[ax], runner, base)
        nested[f"Auswahl Achse {ax}"] = evaluate(st, base, Dbase, boot)
        nested_r[f"Auswahl Achse {ax}"] = evaluate(st, base, Dbase, boot, recal=True)
    for r in range(5):
        st = stitch(chosen_combo[r], runner, base)
        nested[f"Auswahl Kombination Rang {r + 1}"] = evaluate(st, base, Dbase, boot)
        nested_r[f"Auswahl Kombination Rang {r + 1}"] = evaluate(st, base, Dbase, boot, recal=True)

    # ---- Total: Sommer-Regression der Off/Def-Werte
    total_runs = {}
    for tk in TOTAL_KEEP[1:]:
        total_runs[tk] = evaluate(runner.get(cfg(total_keep=tk)), base, Dbase, boot)
    t_tot = time.perf_counter()

    # ------------------------------------------------------------------ Ausgabe
    write(f"\nGitter: {len(axes['carry'])} carry-, {len(axes['hca'])} hca-, {len(axes['movk'])} MOV/K-Werte (Einzelachsen), Kombinationen aus den je 2 besten Werten je Achse.")
    rows = []
    for ax, lst in axes.items():
        for c in lst:
            if ckey(c) == ckey(cfg()):
                continue
            ev = results[ckey(c)]
            win, why = verdict(ev)
            rows.append((label(c), ev, ("GEWINN " if win else "kein Gewinn ") + why))
    keys_in_order = [ckey(c) for lst in axes.values() for c in lst if ckey(c) != ckey(cfg())]
    rows_r = [(lab, results_r[k], None) for (lab, _ev, _x), k in zip(rows, keys_in_order)]
    rows_r = [(lab, ev, ("GEWINN " if verdict(ev)[0] else "kein Gewinn ") + verdict(ev)[1]) for lab, ev, _x in rows_r]
    for title, mk in (("Markt 1: Sieger", ["s_hit", "s_brier", "s_ll"]), ("Markt 2: Spread", ["sp_mae", "sp_bias", "sp_hit"]),
                      ("Markt 4a: Team Total Heim", ["th_mae", "th_bias", "th_cal"]), ("Markt 4b: Team Total Gast", ["ta_mae", "ta_bias", "ta_cal"])):
        market_table(title + " – Einzelachsen, Skala FEST (Faktor 50)", mk, rows, write)
        if title != "Markt 1: Sieger":
            market_table(title + " – Einzelachsen, Skala NEU angepasst", mk, [("Baseline, Skala neu", results_r[ckey(cfg())], None)] + rows_r, write)
    write("\nMarkt 3: Total – Rating-Parameter aendern den Total nicht (er haengt nur an Off/Def); Differenz dort = 0. Total-Aenderungen siehe Abschnitt Total.")

    write("\n=== Walk-forward-Auswahl (nur Saisons < S zur Wahl; Bewertung auf S, zusammengesetzt) ===")
    for S, t in top_log.items():
        write(f"  S = {S}: Baseline innerer Brier {t['inner_score_baseline']}; gewaehlt je Achse: {t['achsen']}")
        write(f"           Kombinationen (Rang 1-5): " + " | ".join(f"{a} [{b}]" for a, b in t["kombinationen"]))
    nrows = []
    for lab, ev in nested.items():
        win, why = verdict(ev)
        nrows.append((lab, ev, ("GEWINN " if win else "kein Gewinn ") + why))
    nrows_r = [(lab, ev, ("GEWINN " if verdict(ev)[0] else "kein Gewinn ") + verdict(ev)[1]) for lab, ev in nested_r.items()]
    for title, mk in (("Markt 1: Sieger", ["s_hit", "s_brier", "s_ll"]), ("Markt 2: Spread", ["sp_mae", "sp_bias", "sp_hit"]),
                      ("Markt 4a: Team Total Heim", ["th_mae", "th_bias", "th_cal"]), ("Markt 4b: Team Total Gast", ["ta_mae", "ta_bias", "ta_cal"])):
        market_table(title + " – Walk-forward-Auswahl, Skala FEST (Faktor 50)", mk, nrows, write)
        if title != "Markt 1: Sieger":
            market_table(title + " – Walk-forward-Auswahl, Skala NEU angepasst", mk, nrows_r, write)

    write("\n=== Markt 3: Total / Sommer-Regression der Off/Def-Werte (nur messen) ===")
    trows = [(f"Total-carry {tk:g}", ev, None) for tk, ev in total_runs.items()]
    market_table("Total", ["t_mae", "t_bias"], trows, write)
    market_table("Team Total Heim (haengt am Total)", ["th_mae", "th_bias"], trows, write)
    market_table("Team Total Gast (haengt am Total)", ["ta_mae", "ta_bias"], trows, write)
    write("\n  Saisonstart-Bias des Totals je Saison (Prognose minus Ergebnis, erste 20 Spiele je Team, Regular Season), Punkte; Rating-Parameter aendern ihn nicht:")
    write(f"    {'Variante':<18}" + "".join(f"{S:>10}" for S in TEST_SEASONS) + f"{'MAE alle 5':>12}")
    season_bias = {}
    for tk in TOTAL_KEEP:
        V = runner.get(cfg(total_keep=tk))
        vals, maes = [], []
        for S in TEST_SEASONS:
            m = window(arr, S, True)
            vals.append(float((V["tp"][m] - arr["total"][m]).mean()))
        mall = np.zeros(len(arr["season"]), bool)
        for S in TEST_SEASONS:
            mall |= window(arr, S, True)
        season_bias[str(tk)] = {"bias_je_saison": {str(S): rnd(v, 3) for S, v in zip(TEST_SEASONS, vals)}, "mae_erste20_2021-25": rnd(np.abs(V["tp"][mall] - arr["total"][mall]).mean(), 3)}
        write(f"    {('Total-carry ' + format(tk, 'g')) if tk != 1.0 else 'Baseline (1.0)':<18}" + "".join(f"{v:>+10.2f}" for v in vals) + f"{season_bias[str(tk)]['mae_erste20_2021-25']:>12.2f}")

    write("\n=== Markt 4: Kalibrierung Team Total Ueber/Unter, Sigma 12,5, Test-Linien Prognose(gerundet) -12 ... +12 (+0,5); Baseline, Fenster b (alle 2023-25) ===")
    tp_, sp_ = base["tp"], base["sp"]
    cal = {}
    cal["heim"] = calib_table((tp_ + sp_) / 2, (arr["total"] + arr["margin"]) / 2, masks["b_alle_2023-25"], write, "Heim-Punkte")
    cal["gast"] = calib_table((tp_ - sp_) / 2, (arr["total"] - arr["margin"]) / 2, masks["b_alle_2023-25"], write, "Gast-Punkte")
    best = stitch(chosen_combo[0], runner, base)
    write("  Rang-1-Kombination der Walk-forward-Auswahl, Fenster b:")
    cal["heim_rang1"] = calib_table((best["tp"] + best["sp"]) / 2, (arr["total"] + arr["margin"]) / 2, masks["b_alle_2023-25"], write, "Heim-Punkte")
    cal["gast_rang1"] = calib_table((best["tp"] - best["sp"]) / 2, (arr["total"] - arr["margin"]) / 2, masks["b_alle_2023-25"], write, "Gast-Punkte")

    sha_after = {f.name: sha(f) for f in files}
    t_end = time.perf_counter()
    timing = {"vorpruefung_laden": round(t_axes - T0 - 0, 1), "einzelachsen_bis_hier": round(t_axes - T0, 1), "auswahl": round(t_sel - t_axes, 1), "total_studie": round(t_tot - t_sel, 1),
              "gesamt": round(t_end - T0, 1), "lauefe_nachbau": runner.n_runs, "sekunden_nachbau": round(runner.t_run, 1), "sekunden_wahrscheinlichkeiten": round(runner.t_prob, 1)}
    write(f"\nLaufzeit gesamt {timing['gesamt']} s ({runner.n_runs} Nachbau-Laeufe: {timing['sekunden_nachbau']} s Rating-Lauf, {timing['sekunden_wahrscheinlichkeiten']} s Wahrscheinlichkeiten)")
    write("SHA vor/nach: " + ("alle unveraendert (" + ", ".join(sha_before) + ")" if sha_before == sha_after else f"ABWEICHUNG {sha_before} -> {sha_after}"))

    def pack(ev):
        return {w: {k: [rnd(x, 5) for x in v] for k, v in d.items()} for w, d in ev.items()}
    out = {"version": 1, "bootstrap": {"ziehungen": N_BOOT, "intervall": "95 %"}, "metriken": {k: {"markt": m, "name": n, "faktor_anzeige": f} for k, m, n, f in METRICS},
           "feld_format": "[Differenz Variante - Baseline, untere Grenze, obere Grenze, Absolutwert der Variante]",
           "einzelachsen": {label(json.loads(k)): {"parameter": json.loads(k), "skala_fest": pack(ev), "gewinn_skala_fest": verdict(ev)[0], "regel_skala_fest": verdict(ev)[1],
                                                "skala_neu": pack(results_r[k]), "gewinn_skala_neu": verdict(results_r[k])[0], "regel_skala_neu": verdict(results_r[k])[1]} for k, ev in results.items()},
           "baseline_skala_neu": pack(results_r[ckey(cfg())]),
           "walk_forward_auswahl": {"je_saison": {str(S): t for S, t in top_log.items()}, "ergebnis": {k: {"skala_fest": pack(ev), "gewinn_skala_fest": verdict(ev)[0], "regel_skala_fest": verdict(ev)[1],
                                                                                   "skala_neu": pack(nested_r[k]), "gewinn_skala_neu": verdict(nested_r[k])[0], "regel_skala_neu": verdict(nested_r[k])[1]} for k, ev in nested.items()}},
           "total_carry": {f"{tk:g}": pack(ev) for tk, ev in total_runs.items()}, "total_saisonstart": season_bias, "kalibrierung_team_total_fenster_b": cal,
           "pruefung": {"nachbau_gleich_baseline": bool(same), "pickle": chk["ok"], "sha_vorher": sha_before, "sha_nachher": sha_after}, "laufzeit_sekunden": timing}
    p = RESULTS / "tuning_grid.json"
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    write(f"Geschrieben: {p.relative_to(ROOT)} ({p.stat().st_size / 1024:.0f} KB)")
    return 0 if sha_before == sha_after else 3


if __name__ == "__main__":
    sys.exit(main())

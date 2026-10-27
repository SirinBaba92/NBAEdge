"""
Informationswert-Test fuer die Spieler-Prognose: Liefert das Modell zusaetzliche Information zu den Betano-Chancen, oder sind die Betano-Chancen allein schon so gut? UNGEPRUEFT.
NUR LESEND (Snapshots und Recorder-/Liga-Ergebnisse wie analysis/eval_player_forecasts.py), kein Netz, aendert weder Modell noch App. Schreibt NUR analysis/results/info_value_test.txt (und .json).

Aufruf (ohne Argumente, wertet automatisch ALLE vollstaendig auswertbaren Tage aus):  venv/bin/python analysis/info_value_test.py        Selbsttest:  --selftest (schreibt nichts)

Daten: analysis/results/forecast_snapshots/<Tag>.json (ohne Ausfall-Variante), nur Spiele, deren Snapshot VOR dem Anpfiff erstellt wurde und fuer die Ergebnisse vorliegen (eval_player_forecasts.game_results),
nur Spieler mit Einsatz (> 0 Minuten) und Prognose, nur Over-Meilensteine mit Betano-Leiter. Betano-Chance = 1 / Quote (enthaelt die Marge). Modell-Chance einmal "roh" (p_ge_raw), einmal "Teamabgleich" (p_ge_adjusted).
1. Mischung p_mix(w) = (1 - w) * p_betano + w * p_modell, w = 0,0 ... 1,0 (Brier); Differenz zu w = 0 fuer das beste w, fuer w = 0,2 und w = 0,5, Bootstrap NACH SPIELERN ((Tag, Spieler) als Gruppe).
   Zusaetzlich: w auf den uebrigen Tagen gewaehlt und am jeweiligen Tag bewertet (Kreuzvalidierung nach Tagen) und w in jeder Bootstrap-Ziehung neu gewaehlt (zeigt den Optimismus der Wahl).
2. Logistische Regression Treffer ~ a + b1 * logit(p_betano) + b2 * logit(p_modell) (b2 deutlich > 0: zusaetzliche Information; b2 nahe 0: keine; a faengt die Marge ab), Intervalle per Bootstrap nach Spielern.
3. Je Tag: Brier bei w = 0, 0,2, 0,5 und Vorzeichen der Differenz.  4. Aufteilungen: Rolle, Stars, Position in der Leiter (Brier w = 0 gegen w = 0,2).
KLEINE STICHPROBE: die Spieler sind die unabhaengigen Beobachtungen (nicht die Zeilen); Ergebnis nur ein erster Hinweis. Reine Beschreibung, keine Empfehlung zur Aenderung der App.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_player_forecasts as ev  # noqa: E402

OUT = ROOT / "analysis" / "results"
OUT_TXT, OUT_JSON = "info_value_test.txt", "info_value_test.json"
W = np.round(np.arange(0.0, 1.0001, 0.1), 1)
KINDS = ("raw", "team")
KN = {"raw": "roh", "team": "Teamabgleich"}
B_MIX, B_REG = 1000, 300


# ----------------------------------------------------------------------------------------------- Daten
def ladder_main(quotes):
    return min(quotes, key=lambda q: (abs(q["odds"] - 2.0), q["milestone"]))["milestone"]


def load_rows():
    """Zeilen aller auswertbaren Spiele. Rueckgabe (rows, info) mit Angaben zu eingeschlossenen und ausgeschlossenen Tagen/Spielen."""
    snaps = ev.load_snapshots(ev.snapshot_dir())
    rows = []
    info = {"tage_in_snapshots": list(snaps), "ausgeschlossen_nach_anpfiff": [], "ausgeschlossen_ohne_ergebnis": [], "spieler_ohne_einsatz": 0, "spieler_ohne_prognose": 0, "spiele": 0}
    ids = {}
    for day, data in snaps.items():
        for key, e in data["games"].items():
            name = f"{day} {key.split('|')[3]} @ {key.split('|')[2]}"
            if e.get("created_after_start"):
                info["ausgeschlossen_nach_anpfiff"].append(name)
                continue
            res, _src = ev.game_results(day, e)
            if res is None:
                info["ausgeschlossen_ohne_ergebnis"].append(name)
                continue
            info["spiele"] += 1
            for p in e["players"]:
                got = res.get(int(p["person_id"]))
                if not got or got["minutes"] <= 0:
                    info["spieler_ohne_einsatz"] += 1
                    continue
                if not p["ok"]:
                    info["spieler_ohne_prognose"] += 1
                    continue
                cid = ids.setdefault((day, p["person_id"]), len(ids))
                qs = sorted(p["quotes"], key=lambda q: q["milestone"])
                main = ladder_main(qs)
                for q in qs:
                    n = q["milestone"]
                    rows.append({"day": day, "game": key, "cl": cid, "hit": int(got["points"] >= n), "odds": q["odds"], "bookmaker": 1.0 / q["odds"], "raw": p["p_ge_raw"][str(n)], "team": p["p_ge_adjusted"][str(n)],
                                 "emin_raw": p["minutes"]["mean"], "epts_raw": p["expected_points_raw"], "pos_low": n == qs[0]["milestone"], "pos_main": n == main, "pos_high": n == qs[-1]["milestone"]})
    info["tage_ausgewertet"] = sorted({r["day"] for r in rows})
    info["tage_ausgeschlossen"] = sorted(set(info["tage_in_snapshots"]) - set(info["tage_ausgewertet"]))
    return rows, info


# ----------------------------------------------------------------------------------------------- Rechnung
def logit(p):
    p = np.clip(p, 0.01, 0.99)
    return np.log(p / (1 - p))


def fit_lr(X, y, ridge=1e-6):
    def f(b):
        z = X @ b
        return float(-(y * np.log(np.clip(expit(z), 1e-12, 1)) + (1 - y) * np.log(np.clip(1 - expit(z), 1e-12, 1))).sum() + ridge * (b ** 2).sum())
    g = lambda b: X.T @ (expit(X @ b) - y) + 2 * ridge * b
    r = minimize(f, np.zeros(X.shape[1]), jac=g, method="BFGS")
    return r.x, float(-r.fun)


def analyze(R, b_mix=B_MIX, b_reg=B_REG, seed=1):
    y = np.array([r["hit"] for r in R], float)
    pb = np.array([r["bookmaker"] for r in R]); cl = np.array([r["cl"] for r in R], int); G = int(cl.max()) + 1
    day = np.array([r["day"] for r in R])
    pm = {k: np.array([r[k] for r in R], float) for k in KINDS}
    idx = np.random.default_rng(seed).integers(0, G, (b_mix, G))
    loss = lambda p: (p - y) ** 2
    mixp = lambda k, w: (1 - w) * pb + w * pm[k]
    clsum = lambda v, m=None: np.bincount(cl if m is None else cl[m], weights=v if m is None else v[m], minlength=G)
    brier = lambda p, m=None: float(loss(p).mean() if m is None else loss(p)[m].mean())

    def diff_ci(d, m=None):
        n, s = clsum(np.ones(len(d)), m), clsum(d, m)
        den = n[idx].sum(1)
        ok = den > 0
        r = s[idx].sum(1)[ok] / den[ok]
        return float(s.sum() / n.sum()), float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))

    base = loss(pb)
    res = {"umfang": {"zeilen": len(R), "spieler": int(len(set(cl))), "spiele": len({r["game"] for r in R}), "tage": sorted(set(day.tolist())), "trefferquote": float(y.mean())}, "brier_betano": brier(pb), "mischung": {}, "regression": {}}
    for k in KINDS:
        tab = {f"{w:.1f}": brier(mixp(k, w)) for w in W}
        wbest = float(min(W, key=lambda w: tab[f"{w:.1f}"]))
        out = {"brier_nach_w": tab, "w_best": wbest}
        for nm, w in (("w_best", wbest), ("w_0_2", 0.2), ("w_0_5", 0.5), ("w_1_0", 1.0)):
            d = diff_ci(loss(mixp(k, w)) - base)
            out[nm] = {"w": w, "brier": brier(mixp(k, w)), "differenz_zu_w0": d[0], "ci95": [d[1], d[2]]}
        days = sorted(set(day))
        if len(days) >= 2:                                         # Kreuzvalidierung nach Tagen
            cv, chosen = np.zeros(len(y)), {}
            for d_ in days:
                tr, te = day != d_, day == d_
                wb = float(min(W, key=lambda w: loss(mixp(k, w))[tr].mean()))
                chosen[d_] = wb
                cv[te] = loss(mixp(k, wb))[te]
            dd = diff_ci(cv - base)
            out["cv_nach_tagen"] = {"gewaehlt": chosen, "differenz_zu_w0": dd[0], "ci95": [dd[1], dd[2]]}
        L = np.stack([loss(mixp(k, w)) for w in W])
        S = np.stack([clsum(L[i]) for i in range(len(W))])
        nn = clsum(np.ones(len(y)))
        sums = S[:, idx].sum(2) / np.maximum(nn[idx].sum(1)[None, :], 1e-9)
        bi = sums.argmin(0)
        gain = sums[bi, np.arange(b_mix)] - sums[0]
        out["w_neu_gewaehlt_je_ziehung"] = {"differenz_mittel": float(gain.mean()), "ci95": [float(np.percentile(gain, 2.5)), float(np.percentile(gain, 97.5))]}
        res["mischung"][k] = out
    by_cl = [np.nonzero(cl == c)[0] for c in range(G)]
    X1 = np.column_stack([np.ones(len(y)), logit(pb)])
    b1, ll1 = fit_lr(X1, y)
    res["regression"]["nur_betano"] = {"a": float(b1[0]), "b1": float(b1[1]), "loglik": ll1}
    for k in KINDS:
        X = np.column_stack([np.ones(len(y)), logit(pb), logit(pm[k])])
        b, ll = fit_lr(X, y)
        bs = np.array([fit_lr(X[ii], y[ii])[0] for ii in (np.concatenate([by_cl[c] for c in idx[t]]) for t in range(min(b_reg, b_mix)))])
        ci = lambda j: [float(np.percentile(bs[:, j], 2.5)), float(np.percentile(bs[:, j], 97.5))]
        res["regression"][k] = {"a": float(b[0]), "a_ci95": ci(0), "b1": float(b[1]), "b1_ci95": ci(1), "b2": float(b[2]), "b2_ci95": ci(2), "loglik": ll, "loglik_gewinn_gegen_nur_betano": ll - ll1,
                                "korrelation_logit": float(np.corrcoef(logit(pb), logit(pm[k]))[0, 1])}
    res["tage"] = {}
    for d_ in sorted(set(day)):
        m = day == d_
        row = {"zeilen": int(m.sum()), "spieler": int(len(set(cl[m]))), "brier_betano": brier(pb, m)}
        for k in KINDS:
            row[k] = {f"w0_{int(w * 10)}": brier(mixp(k, w), m) for w in (0.2, 0.5)}
            row[k].update({"differenz_w0_2": brier(mixp(k, 0.2), m) - brier(pb, m), "differenz_w0_5": brier(mixp(k, 0.5), m) - brier(pb, m)})
        res["tage"][d_] = row
    emin = np.array([r["emin_raw"] for r in R]); epts = np.array([r["epts_raw"] for r in R])
    masks = {"Rolle unter 20 Min": emin < 20, "Rolle 20-28 Min": (emin >= 20) & (emin <= 28), "Rolle ueber 28 Min": emin > 28, "Stars (erw. Punkte roh >= 20)": epts >= 20, "Rest (unter 20)": epts < 20,
             "niedrigster Meilenstein": np.array([r["pos_low"] for r in R]), "Hauptlinie (Quote nahe 2,0)": np.array([r["pos_main"] for r in R]), "hoechster Meilenstein": np.array([r["pos_high"] for r in R])}
    res["aufteilung"] = {}
    for nm, m in masks.items():
        if m.sum() < 20:
            continue
        row = {"zeilen": int(m.sum()), "spieler": int(len(set(cl[m]))), "brier_betano": brier(pb, m)}
        for k in KINDS:
            d = diff_ci(loss(mixp(k, 0.2)) - base, m)
            row[k] = {"brier_w0_2": brier(mixp(k, 0.2), m), "differenz": d[0], "ci95": [d[1], d[2]], "brier_modell_allein": brier(pm[k], m)}
        res["aufteilung"][nm] = row
    return res


# ----------------------------------------------------------------------------------------------- Text
def sig(ci):
    return "abgesichert (Intervall ohne 0)" if (ci[1] < 0 or ci[0] > 0) else "nicht abgesichert (Intervall enthält 0)"


def summary(res, info):
    u, M, Rg = res["umfang"], res["mischung"], res["regression"]
    L = [f"ZUSAMMENFASSUNG Informationswert-Test (UNGEPRÜFT; {u['zeilen']} Zeilen, {u['spieler']} Spieler-Tage, {u['spiele']} Spiele, {len(u['tage'])} Tage: {', '.join(d[5:] for d in u['tage'])}). Spieler sind die unabhängigen Beobachtungen: kleine Stichprobe, nur ein erster Hinweis; Betano = 1/Quote inkl. Marge.",
         f"Betano allein: Brier {res['brier_betano']:.4f}; Trefferquote {100 * u['trefferquote']:.1f} %."]
    for k in KINDS:
        m = M[k]
        L.append(f"Mischung mit Modell {KN[k]}: Brier nach w (0 / 0,2 / 0,5 / 1,0): {m['brier_nach_w']['0.0']:.4f} / {m['brier_nach_w']['0.2']:.4f} / {m['brier_nach_w']['0.5']:.4f} / {m['brier_nach_w']['1.0']:.4f}; bestes w = {m['w_best']['w']:.1f} "
                 f"(Differenz zu w = 0: {m['w_best']['differenz_zu_w0']:+.4f} [{m['w_best']['ci95'][0]:+.4f}; {m['w_best']['ci95'][1]:+.4f}], {sig(m['w_best']['ci95'])}).")
        cv = m.get("cv_nach_tagen")
        L.append(f"   feste Werte: w = 0,2: {m['w_0_2']['differenz_zu_w0']:+.4f} [{m['w_0_2']['ci95'][0]:+.4f}; {m['w_0_2']['ci95'][1]:+.4f}], w = 0,5: {m['w_0_5']['differenz_zu_w0']:+.4f} [{m['w_0_5']['ci95'][0]:+.4f}; {m['w_0_5']['ci95'][1]:+.4f}]"
                 + (f"; w nach Tagen kreuzvalidiert: {cv['differenz_zu_w0']:+.4f} [{cv['ci95'][0]:+.4f}; {cv['ci95'][1]:+.4f}]" if cv else "") + f"; Modell allein (w = 1): {m['w_1_0']['differenz_zu_w0']:+.4f}.")
    for k in KINDS:
        r = Rg[k]
        b2 = r["b2"]; c2 = r["b2_ci95"]
        deut = "deutlich über 0: das Modell liefert zusätzliche Information" if c2[0] > 0 else ("Intervall enthält 0: kein belegter Zusatz" if c2[1] >= 0 else "unter 0")
        L.append(f"Regression {KN[k]}: b2 (Modell) {b2:+.2f} [{c2[0]:+.2f}; {c2[1]:+.2f}] - {deut}; b1 (Betano) {r['b1']:+.2f} [{r['b1_ci95'][0]:+.2f}; {r['b1_ci95'][1]:+.2f}]; Achsenabschnitt a {r['a']:+.2f} (Marge); Korrelation der Logits {r['korrelation_logit']:.2f}.")
    for k in KINDS:
        dirs = {d: (t[k]["differenz_w0_2"] < 0) for d, t in res["tage"].items()}
        L.append(f"Richtung je Tag ({KN[k]}, w = 0,2 gegen w = 0): " + ", ".join(f"{d[5:]} {res['tage'][d][k]['differenz_w0_2']:+.4f}" for d in dirs) + f" -> {'an allen Tagen gleich (Mischung besser)' if all(dirs.values()) else ('an allen Tagen gleich (Mischung schlechter)' if not any(dirs.values()) else 'nicht an allen Tagen gleich')}.")
    L.append("Nur Beschreibung; keine Empfehlung zur Änderung der App. Aus den Teilmengen (Rolle, Stars, Leiter) siehe Abschnitt 4.")
    if info.get("tage_ausgeschlossen") or info["ausgeschlossen_nach_anpfiff"] or info["ausgeschlossen_ohne_ergebnis"]:
        L.append(f"Ausgeschlossen: Tage {', '.join(info['tage_ausgeschlossen']) or '-'}; nach Anpfiff erstellt: {len(info['ausgeschlossen_nach_anpfiff'])} Spiele; ohne Ergebnis: {len(info['ausgeschlossen_ohne_ergebnis'])} Spiele.")
    return L


def tbl(rows, cols, head):
    w = [max(len(h), max((len(str(r[c])) for r in rows), default=0)) for c, h in zip(cols, head)]
    line = lambda v: "  ".join(str(x).rjust(wi) for x, wi in zip(v, w))
    return [line(head), line(["-" * wi for wi in w])] + [line([r[c] for c in cols]) for r in rows]


def render(res, info, runtime):
    L = summary(res, info) + ["", "=" * 120, f"Informationswert-Test, Laufzeit {runtime:.0f} s. Rechenweg: Kopf von analysis/info_value_test.py (Bootstrap nach Spielern).", "=" * 120, ""]
    u = res["umfang"]
    L += ["5. UMFANG", f"  Zeilen {u['zeilen']}, Spieler-Tage (unabhängige Beobachtungen) {u['spieler']}, Spiele {u['spiele']}, Tage {len(u['tage'])} ({', '.join(u['tage'])}); Trefferquote {100 * u['trefferquote']:.1f} %.",
          f"  Snapshots vorhanden für: {', '.join(info['tage_in_snapshots'])}. Ausgeschlossene Tage: {', '.join(info['tage_ausgeschlossen']) or 'keine'}; Spiele mit Snapshot nach Anpfiff: {', '.join(info['ausgeschlossen_nach_anpfiff']) or 'keine'}; Spiele ohne Ergebnis: {', '.join(info['ausgeschlossen_ohne_ergebnis']) or 'keine'}.",
          f"  Spieler ohne Einsatz (nicht gewertet): {info['spieler_ohne_einsatz']}; ohne Prognose: {info['spieler_ohne_prognose']}. Kleine Stichprobe, ungeprüft, nur ein erster Hinweis.", ""]
    L += ["1. MISCHUNG: Brier nach w (w = Gewicht des Modells; w = 0 ist Betano allein)"]
    rows = [{"w": f"{w:.1f}", **{k: f"{res['mischung'][k]['brier_nach_w'][f'{w:.1f}']:.4f}" for k in KINDS}} for w in W]
    L += ["  " + t for t in tbl(rows, ["w", "raw", "team"], ["w", "Modell roh", "Modell Teamabgleich"])]
    for k in KINDS:
        m = res["mischung"][k]
        L += [f"  Modell {KN[k]} - Brier-Differenz zu w = 0 (negativ = besser als Betano allein; Intervall nach Spielern):"]
        for nm, lab in (("w_best", "bestes w"), ("w_0_2", "w = 0,2"), ("w_0_5", "w = 0,5"), ("w_1_0", "w = 1,0 (Modell allein)")):
            x = m[nm]
            L.append(f"    {lab:<24} w {x['w']:.1f}: Brier {x['brier']:.4f}, Differenz {x['differenz_zu_w0']:+.4f} [{x['ci95'][0]:+.4f}; {x['ci95'][1]:+.4f}] - {sig(x['ci95'])}")
        if "cv_nach_tagen" in m:
            c = m["cv_nach_tagen"]
            L.append(f"    w nach Tagen kreuzvalidiert (gewählt: " + ", ".join(f"{d[5:]} {w:.1f}" for d, w in c["gewaehlt"].items()) + f"): Differenz {c['differenz_zu_w0']:+.4f} [{c['ci95'][0]:+.4f}; {c['ci95'][1]:+.4f}]")
        g = m["w_neu_gewaehlt_je_ziehung"]
        L.append(f"    bestes w in jeder Bootstrap-Ziehung neu gewählt: Differenz Ø {g['differenz_mittel']:+.4f} [{g['ci95'][0]:+.4f}; {g['ci95'][1]:+.4f}] (zeigt den Optimismus der Wahl von w)")
    L += ["", "2. LOGISTISCHE REGRESSION Treffer ~ a + b1 * logit(p_Betano) + b2 * logit(p_Modell) (Intervalle: Bootstrap nach Spielern)",
          f"  nur Betano: a {res['regression']['nur_betano']['a']:+.3f}, b1 {res['regression']['nur_betano']['b1']:+.3f}"]
    for k in KINDS:
        r = res["regression"][k]
        L += [f"  Modell {KN[k]}: a {r['a']:+.3f} [{r['a_ci95'][0]:+.3f}; {r['a_ci95'][1]:+.3f}] (Achsenabschnitt: fängt die Betano-Marge ab), b1 {r['b1']:+.3f} [{r['b1_ci95'][0]:+.3f}; {r['b1_ci95'][1]:+.3f}], b2 {r['b2']:+.3f} [{r['b2_ci95'][0]:+.3f}; {r['b2_ci95'][1]:+.3f}]; "
              f"Log-Likelihood-Gewinn gegen nur Betano {r['loglik_gewinn_gegen_nur_betano']:+.2f}; Korrelation der Logits {r['korrelation_logit']:.2f}",
              "    Deutung: b2 deutlich über 0 (Intervall ohne 0) = das Modell hat zusätzliche Information; b2 nahe 0 = keine; b1 unter 1 zeigt, dass Betano allein zu extrem ist."]
    L += ["", "3. JE TAG (Brier-Differenz zur Betano-Chance allein; negativ = Mischung besser)"]
    rows = []
    for d_, t in res["tage"].items():
        rows.append({"d": d_, "n": t["zeilen"], "sp": t["spieler"], "b": f"{t['brier_betano']:.4f}", **{f"{k}2": f"{t[k]['differenz_w0_2']:+.4f}" for k in KINDS}, **{f"{k}5": f"{t[k]['differenz_w0_5']:+.4f}" for k in KINDS}})
    L += ["  " + x for x in tbl(rows, ["d", "n", "sp", "b", "raw2", "raw5", "team2", "team5"], ["Tag", "Zeilen", "Spieler", "Brier Betano", "roh w=0,2", "roh w=0,5", "Team w=0,2", "Team w=0,5"])]
    for k in KINDS:
        s2 = [t[k]["differenz_w0_2"] < 0 for t in res["tage"].values()]
        L.append(f"  {KN[k]} (w = 0,2): Richtung {'an allen Tagen gleich (besser)' if all(s2) else ('an allen Tagen gleich (schlechter)' if not any(s2) else 'nicht an allen Tagen gleich')}; Tage mit Verbesserung {sum(s2)} von {len(s2)}.")
    L += ["", "4. AUFTEILUNG (Brier bei w = 0 gegen w = 0,2; Differenz = w 0,2 minus w 0, Intervall nach Spielern)"]
    rows = []
    for nm, x in res["aufteilung"].items():
        rows.append({"n": nm, "z": x["zeilen"], "sp": x["spieler"], "b0": f"{x['brier_betano']:.4f}", **{f"{k}b": f"{x[k]['brier_w0_2']:.4f}" for k in KINDS}, **{f"{k}d": f"{x[k]['differenz']:+.4f} [{x[k]['ci95'][0]:+.4f}; {x[k]['ci95'][1]:+.4f}]" for k in KINDS}})
    L += ["  " + t for t in tbl(rows, ["n", "z", "sp", "b0", "rawb", "rawd", "teamb", "teamd"], ["Gruppe", "Zeilen", "Spieler", "Brier w=0", "roh w=0,2", "roh Differenz", "Team w=0,2", "Team Differenz"])]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- Selbsttest
def synthetic(model_noise, betano_noise, seed, players=250, per=8, days=4):
    """Kuenstliche Zeilen: wahre Chance je Zeile; Betano = wahre Chance mit Rauschen (+ Marge); Modell = wahre Chance mit Rauschen (model_noise) bzw. reiner Zufall (None)."""
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(players):
        base = rng.normal(-0.2, 1.0)
        shifts = np.linspace(1.2, -1.2, per)
        zt = base + shifts
        pt = expit(zt)
        hit = (rng.random(per) < pt).astype(int)
        zb = zt + rng.normal(0, betano_noise) + rng.normal(0, 0.1, per) - 0.15
        zm = rng.normal(-0.2, 1.0, per) if model_noise is None else zt + rng.normal(0, model_noise) + rng.normal(0, 0.1, per)
        for i in range(per):
            rows.append({"day": f"2026-10-{22 + c % days}", "game": f"g{c // 8}", "cl": c, "hit": int(hit[i]), "odds": float(1 / expit(zb[i])), "bookmaker": float(expit(zb[i])), "raw": float(expit(zm[i])), "team": float(expit(zm[i])),
                         "emin_raw": 20 + 10 * (c % 3), "epts_raw": 10 + 5 * (c % 4), "pos_low": i == 0, "pos_main": i == per // 2, "pos_high": i == per - 1})
    return rows


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    r0 = analyze(synthetic(None, 0.3, 1), b_mix=300, b_reg=150)
    b2 = r0["regression"]["raw"]
    check("Modell reiner Zufall: b2 nahe 0 und Intervall enthaelt 0", abs(b2["b2"]) < 0.25 and b2["b2_ci95"][0] <= 0 <= b2["b2_ci95"][1], (round(b2["b2"], 3), [round(x, 3) for x in b2["b2_ci95"]]))
    check("Modell reiner Zufall: Mischung mit w = 0,5 nicht besser als Betano allein (Differenz >= 0)", r0["mischung"]["raw"]["w_0_5"]["differenz_zu_w0"] > 0 and r0["mischung"]["raw"]["w_best"]["w"] <= 0.2, r0["mischung"]["raw"]["w_best"])
    r1 = analyze(synthetic(0.3, 1.2, 2), b_mix=300, b_reg=150)
    b2 = r1["regression"]["raw"]
    check("Betano verrauscht, Modell nahe an der Wahrheit: b2 gross, deutlich ueber 0", b2["b2"] > 0.6 and b2["b2_ci95"][0] > 0, (round(b2["b2"], 3), [round(x, 3) for x in b2["b2_ci95"]]))
    check("... Mischung besser als Betano allein, abgesichert (w = 0,5 und bestes w)", r1["mischung"]["raw"]["w_0_5"]["differenz_zu_w0"] < 0 and r1["mischung"]["raw"]["w_0_5"]["ci95"][1] < 0 and r1["mischung"]["raw"]["w_best"]["w"] >= 0.5, r1["mischung"]["raw"]["w_best"])
    check("Kreuzvalidierung nach Tagen und je Tag vorhanden, Richtung je Tag gleich (besser)", "cv_nach_tagen" in r1["mischung"]["raw"] and all(t["raw"]["differenz_w0_2"] < 0 for t in r1["tage"].values()))
    r2 = analyze(synthetic(0.3, 0.0, 3), b_mix=300, b_reg=150)
    check("Betano = Wahrheit (kein Rauschen), Modell verrauscht: b2 nahe 0, Mischung schlechter", abs(r2["regression"]["raw"]["b2"]) < 0.4 and r2["mischung"]["raw"]["w_0_5"]["differenz_zu_w0"] > 0)
    info = {"tage_in_snapshots": ["2026-10-22"], "tage_ausgeschlossen": [], "ausgeschlossen_nach_anpfiff": [], "ausgeschlossen_ohne_ergebnis": [], "spieler_ohne_einsatz": 0, "spieler_ohne_prognose": 0}
    txt = render(r1, info, 0.0)
    check("Textbericht: Zusammenfassung <= 15 Zeilen, alle Abschnitte", len(summary(r1, info)) <= 15 and all(f"{i}. " in txt for i in "12345"), len(summary(r1, info)))
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


def main():
    t0 = time.time()
    rows, info = load_rows()
    if len(rows) < 50:
        print("Zu wenige auswertbare Zeilen:", len(rows)); return 1
    res = analyze(rows)
    runtime = time.time() - t0
    res["info"] = info
    res["laufzeit_sekunden"] = round(runtime, 1)
    OUT.mkdir(exist_ok=True)
    (OUT / OUT_TXT).write_text(render(res, info, runtime), encoding="utf-8")
    (OUT / OUT_JSON).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("\n".join(summary(res, info)))
    print(f"\nErgebnisse: {OUT / OUT_TXT}\n            {OUT / OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())

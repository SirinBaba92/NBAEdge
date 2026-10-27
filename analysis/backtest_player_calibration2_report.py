"""
Varianten V1 (breiterer Kern) und V2 (Mittelwert-Unsicherheit) der Meilenstein-Chancen nach Gruppen (Meilenstein-Hoehe, Rolle, Zahl der bisherigen Spiele, Chancen-Stufen, Spielverlauf).
Zwischenstaende von analysis/backtest_player_calibration.py (run, run2). NUR LESEND, schreibt nur analysis/reports/player_calibration2.txt.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_calibration.py report2
Einheit "Zeilen" = Paare Spieler x Meilenstein (k = 5..40). Alle Intervalle 95 %, Bootstrap nach Spielen.
"""
import numpy as np
from scipy.special import expit, logit

import backtest_player_calibration as bc

KS, NK, SEASONS, NB = bc.KS, bc.NK, bc.SEASONS, bc.NB
MIN_ROWS, DEV_MAX = bc.MIN_ROWS, bc.DEV_MAX_PP
L = []
P = L.append

# ------------------------------------------------------------------------------------------------ Daten
parts, g_off = [], 0
v1_parts, v2_parts = [], []
for si, s in enumerate(SEASONS):
    d = np.load(bc.TMP / f"rows_{s}.npz")
    r = {k: d[k] for k in ("gi", "date", "pts", "emin", "mu0", "epts", "ot", "margin", "ntg", "naive", "n", "n_hist")}
    r["gid"] = r["gi"] + g_off
    r["half"] = (r["gi"] >= int(d["n_games"][0]) // 2).astype(int)
    r["season"] = np.full(len(r["gi"]), si)
    r["ppm_cat"], r["wp_cat"], r["off"], r["mk"] = d["ppm_cat"], d["wp_cat"], d["off"], d["mk"]
    parts.append(r)
    v1_parts.append(np.load(bc.TMP / f"var_{s}.npy")[0])
    v2_parts.append(np.load(bc.TMP / f"var2_{s}.npy"))
    g_off += int(d["n_games"][0])
G = g_off
R = {k: np.concatenate([p[k] for p in parts]) for k in ("gid", "half", "season", "date", "pts", "emin", "mu0", "epts", "ot", "margin", "ntg", "naive", "n", "n_hist")}
NR = len(R["gid"])
PA = np.concatenate(v1_parts, axis=0)
VAR2 = np.concatenate(v2_parts, axis=1)
VIDX2 = {n: i for i, n in enumerate(bc.V2NAMES)}
_r = np.random.default_rng(11)
W = np.stack([np.bincount(_r.integers(0, G, G), minlength=G) for _ in range(NB)]).astype(float)

role = np.where(R["mu0"] > 28, 0, np.where(R["mu0"] > 20, 1, 2))
RNAME = ["Starter", "Rotation", "uebrige"]
ref = np.where(np.isfinite(R["naive"]), R["naive"], R["epts"])
rp = np.repeat(np.arange(NR), NK)
kp = np.tile(KS, NR)
hit = (R["pts"][rp] >= kp).astype(float)
gid_p = R["gid"][rp]
dk = kp - ref[rp]
kcls = np.where(dk < -3, 0, np.where(dk <= 3, 1, 2))
KCNAME = ["unter dem Spielerschnitt", "um den Schnitt (+-3)", "ueber dem Schnitt"]
ncls = np.digitize(R["n_hist"], [10, 30, 80])
NCNAME = ["1-9 Spiele", "10-29 Spiele", "30-79 Spiele", "ab 80 Spiele"]
half_p = R["half"][rp]
NP = len(rp)
EPS = 1e-6
allm = np.ones(NP, bool)


def pairs(pm):
    return pm.reshape(-1).astype(float)


def pct(a):
    return np.percentile(a, 2.5, axis=0), np.percentile(a, 97.5, axis=0)


def calib(p, mask, nb=20):
    b = np.minimum((p * nb).astype(int), nb - 1)
    key = gid_p[mask] * nb + b[mask]
    cnt = np.bincount(key, minlength=G * nb).reshape(G, nb).astype(float)
    sp = np.bincount(key, weights=p[mask], minlength=G * nb).reshape(G, nb)
    sh = np.bincount(key, weights=hit[mask], minlength=G * nb).reshape(G, nb)
    n, spt, sht = cnt.sum(0), sp.sum(0), sh.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dev = 100 * (sht - spt) / n
        bs = 100 * (W @ sh - W @ sp) / (W @ cnt)
    lo, hi = pct(bs)
    return {"n": n, "mp": spt / n, "rate": sht / n, "dev": dev, "lo": lo, "hi": hi}


def abw(c):
    n = c["n"]; ok = n > 0
    return float((n[ok] * np.abs(c["dev"][ok])).sum() / n[ok].sum()) if ok.any() else np.nan


def bad_bins(c):
    return [(i, int(c["n"][i]), float(c["dev"][i])) for i in range(len(c["n"])) if c["n"][i] >= MIN_ROWS and abs(c["dev"][i]) > DEV_MAX]


def worst_bin(c):
    cand = [(abs(c["dev"][i]), i) for i in range(len(c["n"])) if c["n"][i] >= MIN_ROWS]
    if not cand:
        return None
    _, i = max(cand)
    return i, int(c["n"][i]), float(c["dev"][i])


def blab(i, nb=20):
    return f"{100*i//nb}-{100*(i+1)//nb}%"


def fit_logit(n, h, x):
    ok = n > 0
    n, h, x = n[ok], h[ok], x[ok]
    a, b = 0.0, 1.0
    for _ in range(30):
        mu = expit(a + b * x); wv = n * mu * (1 - mu) + 1e-12
        g = np.array([(h - n * mu).sum(), ((h - n * mu) * x).sum()])
        H = np.array([[wv.sum(), (wv * x).sum()], [(wv * x).sum(), (wv * x * x).sum()]])
        try:
            st = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            return np.nan, np.nan
        a += st[0]; b += st[1]
        if np.abs(st).max() < 1e-9:
            break
    return a, b


EDGES = np.linspace(-6.0, 6.0, 49)


def slope(p, mask):
    lg = logit(np.clip(p, EPS, 1 - EPS))
    b = np.clip(np.digitize(lg, EDGES) - 1, 0, len(EDGES) - 2)
    nb = len(EDGES) - 1
    key = gid_p[mask] * nb + b[mask]
    cnt = np.bincount(key, minlength=G * nb).reshape(G, nb).astype(float)
    sh = np.bincount(key, weights=hit[mask], minlength=G * nb).reshape(G, nb)
    sx = np.bincount(key, weights=lg[mask], minlength=G * nb).reshape(G, nb)

    def one(c, h, s):
        with np.errstate(invalid="ignore", divide="ignore"):
            x = np.where(c.sum(0) > 0, s.sum(0) / np.maximum(c.sum(0), 1e-12), 0)
        return fit_logit(c.sum(0), h.sum(0), x)
    a0, b0 = one(cnt, sh, sx)
    bs = np.array([one(w_[:, None] * cnt, w_[:, None] * sh, w_[:, None] * sx) for w_ in W])
    if not np.isfinite(b0) or abs(b0) > 5 or np.mean(np.abs(bs[:, 1]) > 5) > 0.05:
        return np.nan, np.nan, np.nan                       # Anpassung nicht stabil (zu wenige Zeilen in den Stufen)
    return b0, np.nanpercentile(bs[:, 1], 2.5), np.nanpercentile(bs[:, 1], 97.5)


def group_stat(p, mask):
    n_g = np.bincount(gid_p[mask], minlength=G).astype(float)
    if n_g.sum() == 0:
        return None
    sp_g = np.bincount(gid_p[mask], weights=p[mask], minlength=G)
    sh_g = np.bincount(gid_p[mask], weights=hit[mask], minlength=G)
    n = n_g.sum()
    bs = 100 * (W @ sh_g - W @ sp_g) / np.maximum(W @ n_g, 1e-12)
    return int(n), sp_g.sum() / n, sh_g.sum() / n, 100 * (sh_g.sum() - sp_g.sum()) / n, np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def scores(p, mask=None):
    m = np.ones(len(p), bool) if mask is None else mask
    pc = np.clip(p[m], EPS, 1 - EPS); h = hit[m]
    return float(np.mean((p[m] - h) ** 2)), float(-np.mean(h * np.log(pc) + (1 - h) * np.log(1 - pc)))


# ------------------------------------------------------------------------------------------------ Kopf
nd = len(set(R["date"].tolist()))
P("VARIANTEN V1 UND V2 DER SPIELER-PUNKTE-CHANCEN NACH GRUPPEN (A roh gegen V1 breiterer Kern und V2 Mittelwert-Unsicherheit), walk-forward, echte Boxscores, ohne Quoten")
P("Skripte analysis/backtest_player_calibration.py (Replay, run2 = Gitter) und analysis/backtest_player_calibration2_report.py (Auswertung); beide lesen nur. Produktivmodell unveraendert.")
P(f"ZAHLEN: {len(SEASONS)} Saisons ({', '.join(SEASONS)}), {nd} Spieltage, {G} Spiele, {NR} Spielerzeilen, {NP} Paare Spieler x Meilenstein (k = 5..40). 'Zeilen' = Paare; Paare einer Spielerzeile/eines Spiels sind abhaengig (Bootstrap nach Spielen).")
P("")
P("KLAERUNG ZUM VORBERICHT (player_calibration.txt): Die Zahlen -5,5 bis -8,9 PP fuer Stufen 80-95 % stehen in der Tabelle 'um den Schnitt (|k - Schnitt| <= 3)' (80-85 %: -5,48; 85-90 %: -7,84; 90-95 %: -8,94). Die 2,7 bis 2,9 PP stammen aus der Gesamttabelle")
P("  ueber alle Meilensteine 5..40. Kein Widerspruch, sondern zwei Gruppen: Die Selbstsicherheit steckt bei Linien nahe am Spielerschnitt (dort liegen die Wetten); die vielen sicheren Chancen weit unter dem Schnitt verduennen das Gesamtbild.")
P("")
P("1 SUCHGITTER UND PARAMETERWAHL")
P("  V1, Lesart f (Faktor): h = c x (1 + 0,05 x); V1, Lesart c (fester Kern): h = c. Beide mit c = 1,0 bis 4,0 in 0,25er-Schritten (13 Werte). (V1f mit c = 1,0 ist A.)")
P("  V2: h^2 = (1 + 0,05 x)^2 + (c / sqrt(n) * x)^2, n = Spiele des Spielers mit mind. 8 Minuten im Verlauf; c = 0,5; 1; 1,5; 2; 2,5; 3; 3,5; 4; 5 (bisher bis 1,0, Optimum lag am Rand).")
P("  Parameterwahl: je Familie der Wert mit dem kleinsten Log-Loss ueber alle Paare der LERNHAELFTE (Hälften = erste/zweite Saisonhälfte nach Datum, beide Saisons gepoolt); angewandt auf die andere Haelfte, und umgekehrt (Kreuz-Anpassung).")
P("  Alle Zahlen fuer V1/V2 unten sind 'ausserhalb der Stichprobe': jede Zeile mit den Parametern, die auf der jeweils anderen Haelfte gewaehlt wurden. Zusatz: Optimum auf den ganzen Daten (nur zur Orientierung, nicht fuer die Regel).")
FAMS = {"V1f": [n for n in bc.V2NAMES if n.startswith("V1f")], "V1c": [n for n in bc.V2NAMES if n.startswith("V1c")], "V2": [n for n in bc.V2NAMES if n.startswith("V2")]}
LABEL = {"A": "A roh", "V1f": "V1 Faktor h=c(1+0,05x)", "V1c": "V1 fester Kern h=c", "V2": "V2 Mittelwert-Unsicherheit"}
ll, abwh = {}, {}
for nm in ["A"] + bc.V2NAMES:
    pm = pairs(PA if nm == "A" else VAR2[VIDX2[nm]])
    pc_ = np.clip(pm, EPS, 1 - EPS)
    l = -(hit * np.log(pc_) + (1 - hit) * np.log(1 - pc_))
    ll[nm] = [float(l[half_p == h].mean()) for h in (0, 1)] + [float(l.mean())]
best, best_all = {}, {}
for f, names in FAMS.items():
    for lh in (0, 1):
        best[(f, lh)] = min(names, key=lambda n: ll[n][lh])
    best_all[f] = min(names, key=lambda n: ll[n][2])
P("  Log-Loss je Parameter (Haelfte 1 / Haelfte 2 / ganz); A: " + " / ".join(f"{x:.4f}" for x in ll["A"]))
for f, names in FAMS.items():
    P(f"    {LABEL[f]}:")
    for n in names:
        mark = "  <- Optimum ganze Daten" if n == best_all[f] else ""
        P(f"      {n.split(' ')[1]:8s} {ll[n][0]:.4f} / {ll[n][1]:.4f} / {ll[n][2]:.4f}{mark}")
    P(f"    gewaehlt: gelernt auf Haelfte 1 -> {best[(f, 0)].split(' ')[1]}; gelernt auf Haelfte 2 -> {best[(f, 1)].split(' ')[1]}; ganze Daten -> {best_all[f].split(' ')[1]}"
      + ("   [ACHTUNG: Optimum am Gitterrand]" if any(best[(f, h)] in (names[0], names[-1]) for h in (0, 1)) or best_all[f] in (names[0], names[-1]) else ""))
CF = {"A": pairs(PA)}
for f in FAMS:
    CF[f] = np.where(half_p == 1, pairs(VAR2[VIDX2[best[(f, 0)]]]), pairs(VAR2[VIDX2[best[(f, 1)]]]))
VARS = list(CF)
P("")

# ------------------------------------------------------------------------------------------------ 2 Gruppen
GROUPS_AB = [("2a Meilenstein-Hoehe: " + KCNAME[i], kcls == i) for i in range(3)] + [("2b Rolle: " + RNAME[i], (role == i)[rp]) for i in range(3)]
GROUPS_C = [("2c Bisherige Spiele: " + NCNAME[i], (ncls == i)[rp]) for i in range(4)]
GROUPS_X = [("Zusatz Spielverlauf: Blowout (Diff >= 20)", (R["margin"] >= 20)[rp]), ("Zusatz Spielverlauf: knapp (Diff < 20)", (R["margin"] < 20)[rp]),
            ("Zusatz Spielverlauf: Verlaengerung", (R["ot"] == 1)[rp]), ("Zusatz Spielverlauf: ohne Verlaengerung", (R["ot"] == 0)[rp]),
            ("Zusatz Saisonphase: erste 15 Teamspiele", (R["ntg"] < 15)[rp]), ("Zusatz Saisonphase: ab 16. Teamspiel", (R["ntg"] >= 15)[rp])]
P("2 KALIBRIERUNG NACH GRUPPEN (Kreuz-Anpassung, ganze Daten). Je Variante: Zeilen, Ø-Abweichung in PP, Steigung b der Rekalibrierung [95 %] (ideal 1; < 1 = zu selbstsicher),")
P("  groesste Stufe mit >= 100 Zeilen (5-%-Stufe, Abweichung in PP = Trefferquote minus Ø-Modell, negativ = Modell zu hoch). Gruppen unter 100 Zeilen sind nicht aussagekraeftig.")
CALG = {}


def group_block(title, mask):
    P(f"  {title}   ({int(mask.sum())} Zeilen{', < 100: nicht aussagekraeftig' if mask.sum() < MIN_ROWS else ''})")
    for v in VARS:
        c = calib(CF[v], mask); CALG[(title, v)] = c
        b0, blo, bhi = slope(CF[v], mask)
        wb = worst_bin(c)
        wbs = f"{blab(wb[0])} ({wb[1]} Z.): {wb[2]:+.1f} PP" if wb else "-"
        P(f"    {LABEL[v]:28s} Zeilen {int(c['n'].sum()):8d}  Ø-Abw. {abw(c):5.2f} PP  Steigung {('n/a (instabil)' if not np.isfinite(b0) else f'{b0:5.3f} [{blo:.3f}; {bhi:.3f}]')}  groesste Stufe: {wbs}")


P("  Gesamt")
group_block("Gesamt (alle Meilensteine)", allm)
for t, m in GROUPS_AB + GROUPS_C + GROUPS_X:
    group_block(t, m)
P("")

P("  2d Modell-Chance-Stufen (5-%-Stufen, ganze Daten, Kreuz-Anpassung): Diff PP (Zeilen) je Variante; 95-%-Intervall der Diff fuer A im Vorbericht. Ab 90 % mit < 100 Zeilen: x = nicht aussagekraeftig, * = < 100 Zeilen.")
P(f"    {'Stufe':10s} " + " ".join(f"{LABEL[v][:24]:>26s}" for v in VARS))
CALT = {v: calib(CF[v], allm) for v in VARS}
for i in range(20):
    cells_ = []
    for v in VARS:
        c = CALT[v]; n = int(c["n"][i])
        mark = "x" if (i >= 18 and n < MIN_ROWS) else ("*" if n < MIN_ROWS else " ")
        cells_.append(f"{c['dev'][i]:+6.2f} [{c['lo'][i]:+5.1f};{c['hi'][i]:+5.1f}] ({n:7d}){mark}" if n else "-")
    P(f"    {blab(i):10s} " + " ".join(f"{s:>26s}" for s in cells_))
P("")

# ------------------------------------------------------------------------------------------------ 3 Regel
P("3 REGEL (Kreuz-Anpassung): Eine Variante zaehlt nur, wenn sie auf BEIDEN Pruefhaelften")
P("  (i) in jeder Gruppe aus 2a und 2b die Ø-Abweichung gegenueber A nicht verschlechtert (Variante <= A) UND insgesamt verbessert (Variante < A), und")
P("  (ii) keine 5-%-Stufe mit >= 100 Zeilen ueber 6 PP daneben hat. (ii) geprueft in zwei Lesarten: R1 = nur Gesamt (wie im Vorbericht); R2 = Gesamt UND in jeder Gruppe aus 2a/2b (streng).")
RULE = {v: {"R1": [], "R2": []} for v in VARS if v != "A"}
for th_, lh_ in ((1, 0), (0, 1)):
    tm = half_p == th_
    P(f"  Pruefhaelfte {th_ + 1} (Parameter gelernt auf Haelfte {lh_ + 1}); {int(tm.sum())} Paare")
    ref_abw = {"Gesamt": abw(calib(CF["A"], tm))}
    for t, m in GROUPS_AB:
        ref_abw[t] = abw(calib(CF["A"], tm & m))
    ref_bad = {"Gesamt": bad_bins(calib(CF["A"], tm))}
    for t, m in GROUPS_AB:
        ref_bad[t] = bad_bins(calib(CF["A"], tm & m))
    P(f"    {'A roh':28s} Ø-Abw. Gesamt {ref_abw['Gesamt']:.2f}; " + "; ".join(f"{t.split(': ')[1][:12]} {ref_abw[t]:.2f}" for t, _ in GROUPS_AB) + f"   | Stufen > 6 PP: Gesamt {len(ref_bad['Gesamt'])}, Gruppen " + str(sum(len(ref_bad[t]) for t, _ in GROUPS_AB)))
    for v in VARS:
        if v == "A":
            continue
        a_all = abw(calib(CF[v], tm))
        ok_i, notes = a_all < ref_abw["Gesamt"], []
        bad_all = bad_bins(calib(CF[v], tm))
        grp_bad = 0
        line = [f"Gesamt {a_all:.2f}"]
        for t, m in GROUPS_AB:
            c = calib(CF[v], tm & m); a_ = abw(c)
            worse = a_ > ref_abw[t] + 1e-12
            if worse:
                ok_i = False; notes.append(t.split(': ')[1])
            gb = bad_bins(c); grp_bad += len(gb)
            line.append(f"{t.split(': ')[1][:12]} {a_:.2f}{'!' if worse else ''}")
        r1 = ok_i and not bad_all
        r2 = ok_i and not bad_all and grp_bad == 0
        RULE[v]["R1"].append(r1); RULE[v]["R2"].append(r2)
        P(f"    {LABEL[v]:28s} Ø-Abw. " + "; ".join(line) + f"   | Stufen > 6 PP: Gesamt {len(bad_all)}, Gruppen {grp_bad}" + (f"   (verschlechtert in: {', '.join(notes)})" if notes else "") + f"  => R1 {'erfuellt' if r1 else 'verfehlt'}, R2 {'erfuellt' if r2 else 'verfehlt'}")
    P("    ('!' = gegenueber A verschlechtert)")
P("  Ergebnis:")
for v in RULE:
    P(f"    {LABEL[v]:28s} R1 (nur Gesamt-Stufen): {'ZAEHLT' if all(RULE[v]['R1']) else 'zaehlt nicht'} ({'/'.join('ja' if x else 'nein' for x in RULE[v]['R1'])}); R2 (auch Gruppen-Stufen): {'ZAEHLT' if all(RULE[v]['R2']) else 'zaehlt nicht'} ({'/'.join('ja' if x else 'nein' for x in RULE[v]['R2'])})")
P("")

# ------------------------------------------------------------------------------------------------ 4 Nebenwirkungen
P("4 NEBENWIRKUNGEN")
P("  4a Ueberkorrektur der Raender (Diff PP = Trefferquote minus Ø-Modell [95 %]; positiv = Modell zu niedrig, negativ = zu hoch). Kreuz-Anpassung, ganze Daten.")
EDGE_SETS = [("Chance < 20 %", lambda p: p < 0.2), ("Chance < 5 %", lambda p: p < 0.05), ("Chance >= 80 %", lambda p: p >= 0.8), ("Chance >= 90 %", lambda p: p >= 0.9), ("Chance >= 95 %", lambda p: p >= 0.95)]
P(f"    {'Rand / Gruppe':34s} " + " ".join(f"{LABEL[v][:24]:>30s}" for v in VARS))
for en, fn in EDGE_SETS:
    for gname, gm in [("alle", allm)] + [(f"Rolle {RNAME[i]}", (role == i)[rp]) for i in range(3)] + [("Zusatz Blowout", (R["margin"] >= 20)[rp]), ("Zusatz knapp", (R["margin"] < 20)[rp])]:
        cells_ = []
        for v in VARS:
            gs = group_stat(CF[v], fn(CF[v]) & gm)
            cells_.append("-" if gs is None else f"{gs[3]:+6.2f} [{gs[4]:+5.1f};{gs[5]:+5.1f}] ({gs[0]:7d}){'*' if gs[0] < MIN_ROWS else ' '}")
        P(f"    {en + ', ' + gname:34s} " + " ".join(f"{s:>30s}" for s in cells_))
P("    (* = unter 100 Zeilen, nicht aussagekraeftig)")
P("")

# Streuung je Variante
P("  4b Streuung: Verhaeltnis echte SD (Ist - Prognose-Mittel) / Modell-SD der jeweiligen Variante [95 %]; 1 = passend. Modell-Streuung = Wurzel aus Ø(Varianz der Punktewerte + Kernbreite h^2) der Variante. Kreuz-Anpassung.")
err = R["pts"] - R["epts"]


def row_var(kind, c, ppm, wp, mk, n):
    x, w = bc.xw(ppm, wp, mk)
    mu = (w * x).sum()
    h0 = 1.0 + 0.05 * x
    if kind == "A":
        h2 = h0 ** 2
    elif kind == "V1f":
        h2 = (c * h0) ** 2
    elif kind == "V1c":
        h2 = np.full_like(x, c * c)
    else:
        h2 = h0 ** 2 + (c / np.sqrt(n) * x) ** 2
    return (w * ((x - mu) ** 2 + h2)).sum()


MV = {v: np.zeros(NR) for v in VARS}
row_i = 0
for pt in parts:
    for j in range(len(pt["gid"])):
        a, b = pt["off"][j], pt["off"][j + 1]
        half = pt["half"][j]
        for v in VARS:
            if v == "A":
                MV[v][row_i] = row_var("A", 0, pt["ppm_cat"][a:b], pt["wp_cat"][a:b], pt["mk"][j], pt["n"][j])
            else:
                nm = best[(v, 1 - half)]
                MV[v][row_i] = row_var(v, float(nm.split("=")[1]), pt["ppm_cat"][a:b], pt["wp_cat"][a:b], pt["mk"][j], pt["n"][j])
        row_i += 1


def ratio(mask, v):
    n = np.bincount(R["gid"][mask], minlength=G).astype(float)
    if n.sum() == 0:
        return None
    s1 = np.bincount(R["gid"][mask], weights=err[mask], minlength=G)
    s2 = np.bincount(R["gid"][mask], weights=err[mask] ** 2, minlength=G)
    sv = np.bincount(R["gid"][mask], weights=MV[v][mask], minlength=G)

    def f(n_, s1_, s2_, sv_):
        return np.sqrt(np.maximum(s2_ / n_ - (s1_ / n_) ** 2, 0) / (sv_ / n_))
    bs = f(W @ n, W @ s1, W @ s2, W @ sv)
    return int(n.sum()), float(f(n.sum(), s1.sum(), s2.sum(), sv.sum())), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


P(f"    {'Gruppe':34s} {'Zeilen':>7s} " + " ".join(f"{LABEL[v][:24]:>26s}" for v in VARS))
SGROUPS = [("alle", np.ones(NR, bool))] + [(f"Rolle {RNAME[i]}", role == i) for i in range(3)] + \
          [("Spielverlauf Blowout", R["margin"] >= 20), ("Spielverlauf knapp", R["margin"] < 20), ("Spielverlauf Verlaengerung", R["ot"] == 1), ("Spielverlauf ohne Verl.", R["ot"] == 0),
           ("Saisonphase erste 15 Teamsp.", R["ntg"] < 15), ("Saisonphase ab 16.", R["ntg"] >= 15)] + [(NCNAME[i], ncls == i) for i in range(4)]
for i in range(3):
    for nm_, mm in (("Blowout", R["margin"] >= 20), ("knapp", R["margin"] < 20)):
        SGROUPS.append((f"Rolle {RNAME[i]} / {nm_}", (role == i) & mm))
for gname, gm in SGROUPS:
    rs = [ratio(gm, v) for v in VARS]
    P(f"    {gname:34s} {rs[0][0]:7d} " + " ".join(f"{r_[1]:7.3f} [{r_[2]:.3f};{r_[3]:.3f}]" .rjust(26) for r_ in rs) + ("   (< 100 Zeilen)" if rs[0][0] < MIN_ROWS else ""))
P("")

# Scores
P("  4c Brier und Log-Loss (Kreuz-Anpassung, ganze Daten)")
for v in VARS:
    br, lg_ = scores(CF[v])
    P(f"    {LABEL[v]:28s} Brier {br:.5f}  Log-Loss {lg_:.5f}")
P("")

# ------------------------------------------------------------------------------------------------ 5 Empfehlung
P("5 EMPFEHLUNG (aus den Zahlen oben; Produktivmodell bleibt unveraendert, 'player-2' waere eine eigene Version neben roh)")
cand = [v for v in RULE if all(RULE[v]["R2"])]
cand1 = [v for v in RULE if all(RULE[v]["R1"])]
scoreLL = {v: scores(CF[v])[1] for v in VARS}
P("  Rangfolge nach Log-Loss (kleiner = besser): " + ", ".join(f"{LABEL[v]} {scoreLL[v]:.5f}" for v in sorted(VARS, key=lambda v: scoreLL[v])))
if cand:
    pick = min(cand, key=lambda v: scoreLL[v])
    P(f"  Regel R2 (streng) erfuellt von: {', '.join(LABEL[v] for v in cand)}. => Empfehlung: {LABEL[pick]} mit Parameter {best_all[pick].split(' ')[1]} (Optimum auf den ganzen Daten; auf den Haelften gewaehlt: {best[(pick, 0)].split(' ')[1]} / {best[(pick, 1)].split(' ')[1]}).")
elif cand1:
    pick = min(cand1, key=lambda v: scoreLL[v])
    P(f"  Regel R2 (streng) von keiner Variante erfuellt; R1 (nur Gesamt-Stufen) erfuellt von: {', '.join(LABEL[v] for v in cand1)}. => Hoechstens {LABEL[pick]} (Parameter {best_all[pick].split(' ')[1]}) als Version neben roh, mit den Einschraenkungen aus 2/3/4.")
else:
    P("  Keine Variante erfuellt die Regel (weder R1 noch R2). => Empfehlung: keine; roh (A) bleibt.")
P("  Hinweis zur Gruppenlage (Ø-Abw. PP, A / V1 Faktor / V1 fest / V2, ganze Daten): " + "; ".join(
    f"{t.split(': ')[1]} " + " / ".join(f"{abw(CALG[(t, v)]):.2f}" for v in VARS) for t, _ in GROUPS_AB if t.startswith("2b")))
P("  Auffaellig: Bei Startern ist A schon gut kalibriert (Steigung 0,92) und alle Varianten ueberkorrigieren (Steigung > 1); bei Rotation und uebrigen sowie bei wenig Verlauf ist A zu selbstsicher. Eine Variante nur fuer Nicht-Starter")
P("  (oder gestaffelt nach Rolle bzw. Zahl der Spiele) waere der naechste Test; er ist hier NICHT gemessen, die Regel oben gilt fuer die Varianten fuer alle Spieler.")
P("  Die Runde davor (player_calibration.txt) hatte V1 (c = 2, Faktor) und V2 (c = 1) nach einer schwaecheren Regel (nur Gesamt-Ø-Abweichung) durchgelassen; unter der strengeren Gruppenregel dieser Runde bestehen sie nicht.")
P("")
P("6 EHRLICHE ZAHLEN")
P(f"  {len(SEASONS)} Saisons, {nd} Spieltage, {G} Spiele, {NR} Spielerzeilen, {NP} Paare. Zeilen je Gruppe/Stufe stehen in den Tabellen 2 und 4; Gruppen/Stufen unter 100 Zeilen sind markiert, Stufen ab 90 % mit < 100 Zeilen als 'x'.")
P("  Paare einer Spielerzeile sind stark abhaengig; Intervalle nach Spielen. Konstanten des Produktivmodells (Blowout-Kurve, league_ppm aus 2025-26) sind fuer 2025-26 teils in-sample. Overtime wird nicht modelliert; Ausfaelle unbekannt (A = 'wenn er spielt').")
P("  Die Parameter werden nach Log-Loss gewaehlt, die Regel misst die Kalibrierung (Ø-Abweichung); das ist bewusst getrennt, damit die Regel nicht auf demselben Mass eingestellt wird, das sie prueft.")
bc.OUT.with_name("player_calibration2.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))

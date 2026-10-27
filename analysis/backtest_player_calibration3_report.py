"""
Verbreiterung der Spieler-Punkte-Chancen NUR fuer Nicht-Starter, gestaffelt nach Rolle und Spielzahl (Varianten W1-W4; Starter immer roh A). NUR LESEND, Produktivmodell unveraendert.
Zwischenstaende von analysis/backtest_player_calibration.py (run, run2). Schreibt nur analysis/reports/player_calibration3.txt.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_calibration.py report3
Rolle = die vor dem Spiel bekannte Rolle der Prognose (pf.role_for_minutes der Basis-Minuten aus dem Verlauf, wie das Feld minutes.role von forecast_player), nie die Ist-Minuten.
Einheit "Zeilen" = Paare Spieler x Meilenstein (k = 5..40). Alle Intervalle 95 %, Bootstrap nach Spielen.
"""
import numpy as np

import backtest_player_calibration as bc
from bt_calib_stats import CalStats

KS, NK, SEASONS, NB = bc.KS, bc.NK, bc.SEASONS, bc.NB
MIN_ROWS = bc.MIN_ROWS
L = []
P = L.append

# ------------------------------------------------------------------------------------------------ Daten
parts, g_off = [], 0
a_parts, v2_parts = [], []
for si, s in enumerate(SEASONS):
    d = np.load(bc.TMP / f"rows_{s}.npz")
    r = {k: d[k] for k in ("gi", "date", "pts", "emin", "mu0", "epts", "ot", "margin", "ntg", "naive", "n", "n_hist")}
    r["gid"] = r["gi"] + g_off
    r["half"] = (r["gi"] >= int(d["n_games"][0]) // 2).astype(int)
    r["ppm_cat"], r["wp_cat"], r["off"], r["mk"] = d["ppm_cat"], d["wp_cat"], d["off"], d["mk"]
    parts.append(r)
    a_parts.append(np.load(bc.TMP / f"var_{s}.npy")[0])
    v2_parts.append(np.load(bc.TMP / f"var2_{s}.npy"))
    g_off += int(d["n_games"][0])
G = g_off
R = {k: np.concatenate([p[k] for p in parts]) for k in ("gid", "half", "date", "pts", "emin", "mu0", "epts", "ot", "margin", "ntg", "naive", "n", "n_hist")}
NR = len(R["gid"])
PA = np.concatenate(a_parts, axis=0)                          # [Zeile, 36]
VAR2 = np.concatenate(v2_parts, axis=1)                       # [Variante, Zeile, 36]
C1, C2 = bc.C1_GRID, bc.C2_GRID
N1, N2 = len(C1), len(C2)
I_V1F, I_V2 = 0, 2 * N1                                        # Startindex der Bloecke in VAR2 (V1f, V1c, V2)
_r = np.random.default_rng(11)
W = np.stack([np.bincount(_r.integers(0, G, G), minlength=G) for _ in range(NB)]).astype(float)

role = np.where(R["mu0"] > 28, 0, np.where(R["mu0"] > 20, 1, 2))      # 0 Starter, 1 Rotation, 2 uebrige (vor dem Spiel bekannt)
RNAME = ["Starter", "Rotation", "uebrige"]
ncls = np.digitize(R["n_hist"], [10, 30, 80])
NCNAME = ["1-9 Spiele", "10-29 Spiele", "30-79 Spiele", "ab 80 Spiele"]
ref = np.where(np.isfinite(R["naive"]), R["naive"], R["epts"])
rp = np.repeat(np.arange(NR), NK)
kp = np.tile(KS, NR)
hit = (R["pts"][rp] >= kp).astype(float)
gid_p = R["gid"][rp]
dk = kp - ref[rp]
kcls = np.where(dk < -3, 0, np.where(dk <= 3, 1, 2))
KCNAME = ["unter dem Spielerschnitt", "um den Schnitt (+-3)", "ueber dem Schnitt"]
half_row = R["half"]
half_p = half_row[rp]
allm = np.ones(NR * NK, bool)
S = CalStats(gid_p, hit, G, W)
hitm = (R["pts"][:, None] >= KS[None, :])
EPS = 1e-6


def row_ll(Pm):
    pc = np.clip(Pm.astype(float), EPS, 1 - EPS)
    return -(np.where(hitm, np.log(pc), np.log(1 - pc))).sum(axis=1)


LL1 = np.array([row_ll(VAR2[I_V1F + i]) for i in range(N1)])      # [c-Index, Zeile]: Summe -log Wahrscheinlichkeit ueber die 36 Meilensteine
LL2 = np.array([row_ll(VAR2[I_V2 + i]) for i in range(N2)])
nonst = role > 0

nd = len(set(R["date"].tolist()))
P("VERBREITERUNG NUR FUER NICHT-STARTER, GESTAFFELT NACH ROLLE UND SPIELZAHL (Varianten W1-W4 gegen A roh), walk-forward, echte Boxscores, ohne Quoten")
P("Skripte analysis/backtest_player_calibration.py (Replay, Gitter) und analysis/backtest_player_calibration3_report.py (Auswertung, mit analysis/bt_calib_stats.py); beide lesen nur. Produktivmodell unveraendert.")
P(f"ZAHLEN: {len(SEASONS)} Saisons ({', '.join(SEASONS)}), {nd} Spieltage, {G} Spiele, {NR} Spielerzeilen, {NR*NK} Paare Spieler x Meilenstein (k = 5..40). 'Zeilen' = Paare; Paare einer Spielerzeile/eines Spiels sind abhaengig (Bootstrap nach Spielen).")
P("ROLLE: vor dem Spiel bekannt = Rolle der Prognose (Basis-Minuten aus dem Verlauf: Starter > 28, Rotation > 20, sonst uebrige); nie die Ist-Minuten. Zeilen je Rolle: " + ", ".join(f"{RNAME[i]} {int((role == i).sum())}" for i in range(3)) + ".")
P("")
P("VARIANTEN (Starter immer unveraendert roh A; Kern h = Breite der Normalglaettung je Punktewert x, A: h = 1 + 0,05 x):")
P("  W1  Rotation/uebrige: h = c_Rolle x (1 + 0,05 x), je Rolle ein c (2 freie Parameter).")
P("  W2  Rotation/uebrige: V2 Mittelwert-Unsicherheit h^2 = (1 + 0,05 x)^2 + (c_Rolle / sqrt(n) x)^2, n = Spiele des Spielers mit mind. 8 Minuten, je Rolle eine Staerke c (2 freie Parameter).")
P("  W3  Nicht-Starter: h = c_Spielzahl x (1 + 0,05 x), je Spielzahl-Klasse (1-9, 10-29, 30-79, ab 80 bisherige Spiele) ein c (4 freie Parameter, fuer Rotation und uebrige gemeinsam).")
P("  W4  W1 und W3 kombiniert: c(Rolle, Spielzahl) = c_Rolle + d_Spielzahl, d fuer 'ab 80' = 0 (5 freie Parameter: 2 Grundwerte + 3 Verschiebungen in 0,25er-Schritten).")
P("")

# ------------------------------------------------------------------------------------------------ 1 Parameterwahl
P("1 PARAMETERWAHL")
P(f"  Gitter: Faktor-Kern c = {C1[0]:g} bis {C1[-1]:g} in 0,25er-Schritten ({N1} Werte, c = 1 ist roh); V2-Staerke c = " + ", ".join(f"{c:g}" for c in C2) + f" ({N2} Werte).")
P("  Wahl: je Parameter der Wert mit dem kleinsten Log-Loss (Summe ueber die Paare) der Zeilen der LERNHAELFTE in der jeweiligen Gruppe (Nicht-Starter der Rolle bzw. der Spielzahl-Klasse); Haelften = erste/zweite Saisonhälfte (nach Datum) beider Saisons.")
P("  W4: Koordinaten-Abstieg ueber Grundwerte und Verschiebungen (5 Durchgaenge). Angewandt wird auf die jeweils ANDERE Haelfte (Kreuz-Anpassung); alle Zahlen unten sind daher ausserhalb der Stichprobe.")


def argmin_rows(LL, mask):
    tot = LL[:, mask].sum(axis=1)
    return int(np.argmin(tot)), tot


def idx_w4(base_, shift_):
    ci = np.zeros(NR, int)
    for r in (1, 2):
        for b in range(4):
            m = (role == r) & (ncls == b)
            ci[m] = int(np.clip(base_[r] + shift_[b], 0, N1 - 1))
    return ci


def learn_params(split):
    """Parameter von W1-W4 je Lernmenge (split == 0 bzw. 1), Rueckgabe {(Variante, Lernmenge): Parameter}."""
    par = {}
    for lh in (0, 1):
        lm = split == lh
        par[("W1", lh)] = {r: argmin_rows(LL1, lm & (role == r))[0] for r in (1, 2)}
        par[("W2", lh)] = {r: argmin_rows(LL2, lm & (role == r))[0] for r in (1, 2)}
        par[("W3", lh)] = {b: argmin_rows(LL1, lm & nonst & (ncls == b))[0] for b in range(4)}
        base = dict(par[("W1", lh)])
        shift = {0: 0, 1: 0, 2: 0, 3: 0}

        def tot_w4(base_, shift_):
            ci = idx_w4(base_, shift_)
            m = lm & nonst
            return LL1[ci[m], np.where(m)[0]].sum()
        for _ in range(5):
            for r in (1, 2):
                base[r] = min(range(N1), key=lambda v: tot_w4({**base, r: v}, shift))
            for b in (0, 1, 2):
                shift[b] = min(range(-8, 9), key=lambda v: tot_w4(base, {**shift, b: v}))
        par[("W4", lh)] = {"base": dict(base), "shift": dict(shift)}
    return par


PAR = learn_params(half_row)

for lh in (0, 1):
    lm = half_row == lh
    P(f"  Lernhaelfte {lh + 1}:")
    for r in (1, 2):
        _, t1 = argmin_rows(LL1, lm & (role == r)); _, t2 = argmin_rows(LL2, lm & (role == r))
        nr_ = int((lm & (role == r)).sum()); lA = LL1[0][lm & (role == r)].sum()
        P(f"    {RNAME[r]} ({nr_} Zeilen): Log-Loss je Paar relativ zu roh (negativ = besser), Faktor-Kern c: " + ", ".join(f"{C1[i]:g}:{(t1[i] - lA) / (nr_ * NK):+.4f}" for i in range(0, N1, 2)) + f"; gewaehlt W1 c = {C1[PAR[('W1', lh)][r]]:g}")
        P(f"      V2-Staerke c: " + ", ".join(f"{C2[i]:g}:{(t2[i] - lA) / (nr_ * NK):+.4f}" for i in range(N2)) + f"; gewaehlt W2 c = {C2[PAR[('W2', lh)][r]]:g}")
    P("    W3 (c je Spielzahl-Klasse): " + ", ".join(f"{NCNAME[b]} c = {C1[PAR[('W3', lh)][b]]:g} ({int((lm & nonst & (ncls == b)).sum())} Zeilen)" for b in range(4)))
    w4 = PAR[("W4", lh)]
    P(f"    W4: Grundwerte Rotation c = {C1[w4['base'][1]]:g}, uebrige c = {C1[w4['base'][2]]:g}; Verschiebung (Klasse 1-9 / 10-29 / 30-79 / ab 80) = " + " / ".join(f"{0.25 * w4['shift'][b]:+.2f}" for b in range(4)))
    edge = []
    for r in (1, 2):
        if PAR[("W1", lh)][r] in (0, N1 - 1):
            edge.append(f"W1 {RNAME[r]}")
        if PAR[("W2", lh)][r] in (0, N2 - 1):
            edge.append(f"W2 {RNAME[r]}")
    for b in range(4):
        if PAR[("W3", lh)][b] in (0, N1 - 1):
            edge.append(f"W3 {NCNAME[b]}")
    if edge:
        P("    [ACHTUNG: Optimum am Gitterrand: " + ", ".join(edge) + "]")
P("")

# ------------------------------------------------------------------------------------------------ Kreuz-Anpassung
def build(vname, PAR, split):
    """Chancen je Zeile (Kreuz-Anpassung): Starter A, Nicht-Starter mit den Parametern der jeweils anderen Haelfte."""
    out = PA.copy()
    cvals = np.ones(NR)                                         # Faktor-Kern c je Zeile (1 = roh), fuer die Varianz
    strength = np.zeros(NR)                                     # V2-Staerke je Zeile (0 = roh)
    for h in (0, 1):
        lh = 1 - h
        for r in (1, 2):
            for b in range(4):
                m = (role == r) & (ncls == b) & (split == h)
                if not m.any():
                    continue
                rows = np.where(m)[0]
                if vname == "W1":
                    i = PAR[("W1", lh)][r]; out[rows] = VAR2[I_V1F + i, rows]; cvals[rows] = C1[i]
                elif vname == "W2":
                    i = PAR[("W2", lh)][r]; out[rows] = VAR2[I_V2 + i, rows]; strength[rows] = C2[i]
                elif vname == "W3":
                    i = PAR[("W3", lh)][b]; out[rows] = VAR2[I_V1F + i, rows]; cvals[rows] = C1[i]
                else:
                    w4 = PAR[("W4", lh)]
                    i = int(np.clip(w4["base"][r] + w4["shift"][b], 0, N1 - 1)); out[rows] = VAR2[I_V1F + i, rows]; cvals[rows] = C1[i]
    return out, cvals, strength


VARS = ["A", "W1", "W2", "W3", "W4"]
LABEL = {"A": "A roh", "W1": "W1 Faktor je Rolle", "W2": "W2 Mittelwert-Unsich. je Rolle", "W3": "W3 Faktor je Spielzahl", "W4": "W4 Rolle + Spielzahl"}
CF, CVAL, STR = {"A": PA.reshape(-1).astype(float)}, {"A": np.ones(NR)}, {"A": np.zeros(NR)}
for v in VARS[1:]:
    pm, cv, st = build(v, PAR, half_row)
    CF[v], CVAL[v], STR[v] = pm.reshape(-1).astype(float), cv, st
assert np.array_equal(CF["W1"][np.repeat(role == 0, NK)], CF["A"][np.repeat(role == 0, NK)]), "Starter muessen roh bleiben"
P("  Kontrolle: Chancen der Starter in W1-W4 sind bitgleich zu A (geprueft).")
P("")

# ------------------------------------------------------------------------------------------------ 2 Kalibrierung
GROUPS = [("2a Meilenstein-Hoehe: " + KCNAME[i], kcls == i) for i in range(3)] + [("2b Rolle: " + RNAME[i], np.repeat(role == i, NK)) for i in range(3)] + \
         [("2c Bisherige Spiele: " + NCNAME[i], np.repeat(ncls == i, NK)) for i in range(4)]
P("2 KALIBRIERUNG NACH GRUPPEN (Kreuz-Anpassung, ganze Daten). Je Variante: Zeilen, Ø-Abweichung in PP (zeilengewichtet ueber die 5-%-Stufen), Steigung b der Rekalibrierung [95 %] (ideal 1; < 1 = zu selbstsicher),")
P("  groesste Stufe mit >= 100 Zeilen (Abweichung = Trefferquote minus Ø-Modell, negativ = Modell zu hoch). Gruppen unter 100 Zeilen sind nicht aussagekraeftig.")


def block(title, mask):
    P(f"  {title}   ({int(mask.sum())} Zeilen{', < 100: nicht aussagekraeftig' if mask.sum() < MIN_ROWS else ''})")
    for v in VARS:
        c = S.calib(CF[v], mask)
        b0, blo, bhi = S.slope(CF[v], mask)
        wb = S.worst_bin(c)
        wbs = f"{S.blab(wb[0])} ({wb[1]} Z.): {wb[2]:+.1f} PP" if wb else "-"
        sl = "n/a (instabil)" if not np.isfinite(b0) else f"{b0:5.3f} [{blo:.3f}; {bhi:.3f}]"
        P(f"    {LABEL[v]:32s} Zeilen {int(c['n'].sum()):8d}  Ø-Abw. {S.abw(c):5.2f} PP  Steigung {sl:26s} groesste Stufe: {wbs}")


block("Gesamt (alle Meilensteine)", allm)
for t, m in GROUPS:
    block(t, m)
P("")
P("  2d Modell-Chance-Stufen (5-%-Stufen, ganze Daten, Kreuz-Anpassung): Diff PP [95 %] (Zeilen). Ab 90 % mit < 100 Zeilen: x = nicht aussagekraeftig, * = < 100 Zeilen.")
P(f"    {'Stufe':8s} " + " ".join(f"{LABEL[v][:22]:>28s}" for v in VARS))
CT = {v: S.calib(CF[v], allm) for v in VARS}
for i in range(20):
    cells_ = []
    for v in VARS:
        c = CT[v]; n = int(c["n"][i])
        mark = "x" if (i >= 18 and n < MIN_ROWS) else ("*" if n < MIN_ROWS else " ")
        cells_.append(f"{c['dev'][i]:+5.2f} [{c['lo'][i]:+5.1f};{c['hi'][i]:+5.1f}] ({n:7d}){mark}" if n else "-")
    P(f"    {S.blab(i):8s} " + " ".join(f"{s:>28s}" for s in cells_))
P("")

# ------------------------------------------------------------------------------------------------ 3 Regel
P("3 REGEL (Kreuz-Anpassung): Eine Variante zaehlt nur, wenn sie auf BEIDEN Pruefhaelften")
P("  (i) in jeder Gruppe aus 2a, 2b und 2c die Ø-Abweichung gegenueber A nicht verschlechtert (Variante <= A; '!' = verschlechtert) UND insgesamt verbessert (Variante < A), und")
P("  (ii) keine 5-%-Stufe mit >= 100 Zeilen ueber 6 PP daneben hat. (ii) in zwei Lesarten: R1 = nur Gesamt; R2 = Gesamt UND in jeder Gruppe 2a/2b/2c (streng). Starter sind in W1-W4 identisch zu A (Differenz 0).")
FAIL = {v: [] for v in VARS[1:]}
RULE = {v: {"R1": [], "R2": []} for v in VARS[1:]}
REFBAD = {}
for th_, lh_ in ((1, 0), (0, 1)):
    tm = half_p == th_
    P(f"  Pruefhaelfte {th_ + 1} (Parameter gelernt auf Haelfte {lh_ + 1}); {int(tm.sum())} Paare")
    cA = {"Gesamt": S.calib(CF["A"], tm)}
    for t, m in GROUPS:
        cA[t] = S.calib(CF["A"], tm & m)
    nbadA = sum(len(S.bad_bins(c)) for c in cA.values())
    P(f"    A roh: Ø-Abw. Gesamt {S.abw(cA['Gesamt']):.2f}; " + "; ".join(f"{t.split(': ')[1][:14]} {S.abw(cA[t]):.2f}" for t, _ in GROUPS) + f"   | Stufen > 6 PP: Gesamt {len(S.bad_bins(cA['Gesamt']))}, Gruppen {nbadA - len(S.bad_bins(cA['Gesamt']))}")
    for v in VARS[1:]:
        cv = {"Gesamt": S.calib(CF[v], tm)}
        for t, m in GROUPS:
            cv[t] = S.calib(CF[v], tm & m)
        worse = [t for t in ["Gesamt"] + [g[0] for g in GROUPS] if t != "Gesamt" and S.abw(cv[t]) > S.abw(cA[t]) + 1e-12]
        improved = S.abw(cv["Gesamt"]) < S.abw(cA["Gesamt"])
        bad_all = S.bad_bins(cv["Gesamt"])
        bad_grp = {t: S.bad_bins(cv[t]) for t, _ in GROUPS}
        nbg = sum(len(x) for x in bad_grp.values())
        ok_i = improved and not worse
        r1 = ok_i and not bad_all
        r2 = r1 and nbg == 0
        RULE[v]["R1"].append(r1); RULE[v]["R2"].append(r2)
        for t in worse:
            FAIL[v].append(f"Haelfte {th_ + 1}: {t} verschlechtert ({S.abw(cA[t]):.2f} -> {S.abw(cv[t]):.2f})")
        if not improved:
            FAIL[v].append(f"Haelfte {th_ + 1}: Gesamt nicht verbessert ({S.abw(cA['Gesamt']):.2f} -> {S.abw(cv['Gesamt']):.2f})")
        for t in bad_grp:
            if bad_grp[t]:
                FAIL[v].append(f"Haelfte {th_ + 1}: {t}: Stufe(n) > 6 PP: " + ", ".join(f"{S.blab(i)} ({n} Z., {d:+.1f})" for i, n, d in bad_grp[t]))
        if bad_all:
            FAIL[v].append(f"Haelfte {th_ + 1}: Gesamt: Stufe(n) > 6 PP: " + ", ".join(f"{S.blab(i)} ({n} Z., {d:+.1f})" for i, n, d in bad_all))
        P(f"    {LABEL[v]:32s} Ø-Abw. Gesamt {S.abw(cv['Gesamt']):.2f}; " + "; ".join(f"{t.split(': ')[1][:14]} {S.abw(cv[t]):.2f}{'!' if t in worse else ''}" for t, _ in GROUPS)
          + f"   | Stufen > 6 PP: Gesamt {len(bad_all)}, Gruppen {nbg}  => R1 {'erfuellt' if r1 else 'verfehlt'}, R2 {'erfuellt' if r2 else 'verfehlt'}")
P("  Wo faellt welche Variante durch (Gruppe, Haelfte):")
for v in VARS[1:]:
    P(f"    {LABEL[v]}:")
    if FAIL[v]:
        for f in FAIL[v]:
            P(f"      - {f}")
    else:
        P("      - keine")
P("  Ergebnis:")
for v in VARS[1:]:
    P(f"    {LABEL[v]:32s} R1 (nur Gesamt-Stufen): {'ZAEHLT' if all(RULE[v]['R1']) else 'zaehlt nicht'} ({'/'.join('ja' if x else 'nein' for x in RULE[v]['R1'])}); R2 (auch Gruppen-Stufen): {'ZAEHLT' if all(RULE[v]['R2']) else 'zaehlt nicht'} ({'/'.join('ja' if x else 'nein' for x in RULE[v]['R2'])})   [Haelfte 2 / Haelfte 1]")
P("")

# ------------------------------------------------------------------------------------------------ 4 Nebenwirkungen
P("4 NEBENWIRKUNGEN")
P("  4a Raender (Diff PP = Trefferquote minus Ø-Modell [95 %]; positiv = Modell zu niedrig, negativ = zu hoch). Kreuz-Anpassung, ganze Daten. * = unter 100 Zeilen (nicht aussagekraeftig).")
P(f"    {'Rand / Gruppe':32s} " + " ".join(f"{LABEL[v][:22]:>30s}" for v in VARS))
EDGE_SETS = [("Chance < 20 %", lambda p: p < 0.2), ("Chance < 5 %", lambda p: p < 0.05), ("Chance >= 80 %", lambda p: p >= 0.8), ("Chance >= 90 %", lambda p: p >= 0.9)]
EG = [("alle", allm)] + [(f"Rolle {RNAME[i]}", np.repeat(role == i, NK)) for i in range(3)] + [(NCNAME[i], np.repeat(ncls == i, NK)) for i in range(4)]
for en, fn in EDGE_SETS:
    for gname, gm in EG:
        cells_ = []
        for v in VARS:
            gs = S.group_stat(CF[v], fn(CF[v]) & gm)
            cells_.append("-" if gs is None else f"{gs[3]:+6.2f} [{gs[4]:+5.1f};{gs[5]:+5.1f}] ({gs[0]:7d}){'*' if gs[0] < MIN_ROWS else ' '}")
        P(f"    {en + ', ' + gname:32s} " + " ".join(f"{s:>30s}" for s in cells_))
P("")
# Streuung
P("  4b Streuung: Verhaeltnis echte SD (Ist - Prognose-Mittel) / Modell-SD der jeweiligen Variante [95 %]; 1 = passend (< 1: Modell zu breit, > 1: zu schmal). Modell-Streuung = Wurzel aus Ø(Varianz der Punktewerte + Kernbreite h^2).")
V0, H0, X2 = np.zeros(NR), np.zeros(NR), np.zeros(NR)
row_i = 0
for pt in parts:
    for j in range(len(pt["gid"])):
        a, b = pt["off"][j], pt["off"][j + 1]
        x, w = bc.xw(pt["ppm_cat"][a:b], pt["wp_cat"][a:b], pt["mk"][j])
        mu = (w * x).sum()
        V0[row_i] = (w * (x - mu) ** 2).sum(); H0[row_i] = (w * (1.0 + 0.05 * x) ** 2).sum(); X2[row_i] = (w * x ** 2).sum()
        row_i += 1
err = R["pts"] - R["epts"]


def mvar(v):
    return V0 + CVAL[v] ** 2 * H0 + (STR[v] ** 2 / np.maximum(R["n"], 1)) * X2


def ratio(mask, v):
    n = np.bincount(R["gid"][mask], minlength=G).astype(float)
    s1 = np.bincount(R["gid"][mask], weights=err[mask], minlength=G)
    s2 = np.bincount(R["gid"][mask], weights=err[mask] ** 2, minlength=G)
    sv = np.bincount(R["gid"][mask], weights=mvar(v)[mask], minlength=G)

    def f(n_, s1_, s2_, sv_):
        return np.sqrt(np.maximum(s2_ / n_ - (s1_ / n_) ** 2, 0) / (sv_ / n_))
    bs = f(W @ n, W @ s1, W @ s2, W @ sv)
    return int(n.sum()), float(f(n.sum(), s1.sum(), s2.sum(), sv.sum())), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


P(f"    {'Gruppe':34s} {'Zeilen':>7s} " + " ".join(f"{LABEL[v][:22]:>26s}" for v in VARS))
SG = [("alle", np.ones(NR, bool))] + [(f"Rolle {RNAME[i]}", role == i) for i in range(3)] + [(NCNAME[i], ncls == i) for i in range(4)] + \
     [(f"{RNAME[r]} / {NCNAME[b]}", (role == r) & (ncls == b)) for r in (1, 2) for b in range(4)]
for gname, gm in SG:
    rs = [ratio(gm, v) for v in VARS]
    P(f"    {gname:34s} {rs[0][0]:7d} " + " ".join(f"{r_[1]:7.3f} [{r_[2]:.3f};{r_[3]:.3f}]".rjust(26) for r_ in rs) + ("   (< 100 Zeilen: nicht aussagekraeftig)" if rs[0][0] < MIN_ROWS else ""))
P("")
P("  4c Brier und Log-Loss (Kreuz-Anpassung, ganze Daten)")
for v in VARS:
    br, lg_ = S.scores(CF[v])
    P(f"    {LABEL[v]:32s} Brier {br:.5f}  Log-Loss {lg_:.5f}")
P("")

# ------------------------------------------------------------------------------------------------ 5 Empfehlung
P("5 EMPFEHLUNG (aus den Zahlen oben; Produktivmodell bleibt unveraendert; 'player-2' waere eine eigene Version neben roh)")
ll_v = {v: S.scores(CF[v])[1] for v in VARS}
P("  Rangfolge nach Log-Loss (kleiner = besser): " + ", ".join(f"{LABEL[v]} {ll_v[v]:.5f}" for v in sorted(VARS, key=lambda v: ll_v[v])))
c2 = [v for v in VARS[1:] if all(RULE[v]["R2"])]
c1 = [v for v in VARS[1:] if all(RULE[v]["R1"])]
if c2 or c1:
    pick = min(c2 or c1, key=lambda v: ll_v[v])
    P(f"  {'R2 (streng)' if c2 else 'Nur R1 (lockere Lesart)'} erfuellt von: {', '.join(LABEL[v] for v in (c2 or c1))}. => Empfehlung: {LABEL[pick]}. Parameter (Haelfte 1 / Haelfte 2 gelernt):")
    for lh in (0, 1):
        if pick in ("W1", "W2"):
            grid = C1 if pick == "W1" else C2
            P(f"    gelernt auf Haelfte {lh + 1}: " + ", ".join(f"{RNAME[r]} c = {grid[PAR[(pick, lh)][r]]:g}" for r in (1, 2)))
        elif pick == "W3":
            P(f"    gelernt auf Haelfte {lh + 1}: " + ", ".join(f"{NCNAME[b]} c = {C1[PAR[('W3', lh)][b]]:g}" for b in range(4)))
        else:
            w4 = PAR[("W4", lh)]
            P(f"    gelernt auf Haelfte {lh + 1}: Grundwerte Rotation c = {C1[w4['base'][1]]:g}, uebrige c = {C1[w4['base'][2]]:g}; Verschiebung " + " / ".join(f"{0.25 * w4['shift'][b]:+.2f}" for b in range(4)))
else:
    nf = {v: len(FAIL[v]) for v in VARS[1:]}
    best = min(nf, key=lambda v: (-sum(RULE[v]["R1"]), ll_v[v]))
    P("  Keine Variante erfuellt die Regel (weder R1 noch R2). => Empfehlung: keine, roh (A) bleibt.")
    P(f"  Bestes Ergebnis: {LABEL[best]} (Auswahl: zuerst Zahl der Pruefhaelften, auf denen die lockere Regel R1 erfuellt ist, dann Log-Loss; R1 erfuellt auf " + ", ".join(f"{LABEL[v]} {sum(RULE[v]['R1'])} von 2" for v in nf) + f"; Log-Loss {ll_v[best]:.5f} gegen A {ll_v['A']:.5f}). Verstoesse von {LABEL[best]}:")
    for f in FAIL[best]:
        P(f"    - {f}")
P("")
P("5b ZUSATZPRUEFUNG: SAISONWEISE GETEILT (Parameter auf einer ganzen Saison gewaehlt, auf der anderen Saison geprueft; reine Zeit-Trennung statt Saisonhaelften)")
SEAS = np.concatenate([np.full(len(p_["gid"]), i) for i, p_ in enumerate(parts)])
sp_p = np.repeat(SEAS, NK)
PAR_S = learn_params(SEAS)
CFS = {"A": CF["A"]}
for v in VARS[1:]:
    CFS[v] = build(v, PAR_S, SEAS)[0].reshape(-1).astype(float)
P("  Parameter (gelernt auf 2024-25 / gelernt auf 2025-26): " + "; ".join(
    f"{LABEL[v]}: " + " / ".join(
        (", ".join(f"{RNAME[r]} {(C1 if v == 'W1' else C2)[PAR_S[(v, lh)][r]]:g}" for r in (1, 2)) if v in ("W1", "W2") else
         ", ".join(f"{NCNAME[b]} {C1[PAR_S[(v, lh)][b]]:g}" for b in range(4)) if v == "W3" else
         f"Rotation {C1[PAR_S[(v, lh)]['base'][1]]:g}, uebrige {C1[PAR_S[(v, lh)]['base'][2]]:g}, Versch. " + "/".join(f"{0.25 * PAR_S[(v, lh)]['shift'][b]:+.2f}" for b in range(4)))
        for lh in (0, 1)) for v in VARS[1:]))
RULE_S = {v: [] for v in VARS[1:]}
for th_, lh_, nm_ in ((1, 0, "Pruefsaison 2025-26 (gelernt 2024-25)"), (0, 1, "Pruefsaison 2024-25 (gelernt 2025-26)")):
    tm = sp_p == th_
    cA = {"Gesamt": S.calib(CFS["A"], tm)}
    for t, m in GROUPS:
        cA[t] = S.calib(CFS["A"], tm & m)
    P(f"  {nm_}; {int(tm.sum())} Paare. A roh: Ø-Abw. Gesamt {S.abw(cA['Gesamt']):.2f}; " + "; ".join(f"{t.split(': ')[1][:12]} {S.abw(cA[t]):.2f}" for t, _ in GROUPS) + f" | Stufen > 6 PP in Gruppen: {sum(len(S.bad_bins(cA[t])) for t, _ in GROUPS)}")
    for v in VARS[1:]:
        cv = {"Gesamt": S.calib(CFS[v], tm)}
        for t, m in GROUPS:
            cv[t] = S.calib(CFS[v], tm & m)
        worse = [t for t, _ in GROUPS if S.abw(cv[t]) > S.abw(cA[t]) + 1e-12]
        improved = S.abw(cv["Gesamt"]) < S.abw(cA["Gesamt"])
        r1 = improved and not worse and not S.bad_bins(cv["Gesamt"])
        RULE_S[v].append(r1)
        P(f"    {LABEL[v]:32s} Ø-Abw. Gesamt {S.abw(cv['Gesamt']):.2f}; " + "; ".join(f"{t.split(': ')[1][:12]} {S.abw(cv[t]):.2f}{'!' if t in worse else ''}" for t, _ in GROUPS)
          + f" | Stufen > 6 PP: Gesamt {len(S.bad_bins(cv['Gesamt']))}, Gruppen {sum(len(S.bad_bins(cv[t])) for t, _ in GROUPS)} => R1 {'erfuellt' if r1 else 'verfehlt'}")
P("  Ergebnis saisonweise (R1): " + "; ".join(f"{LABEL[v]} {'ZAEHLT' if all(RULE_S[v]) else 'zaehlt nicht'} ({'/'.join('ja' if x else 'nein' for x in RULE_S[v])})" for v in RULE_S))
P("")
P("6 EHRLICHE ZAHLEN")
P(f"  {len(SEASONS)} Saisons, {nd} Spieltage, {G} Spiele, {NR} Spielerzeilen, {NR*NK} Paare. Zeilen je Gruppe und Stufe stehen in den Tabellen 2 und 4; Gruppen/Stufen unter 100 Zeilen sind markiert, Stufen ab 90 % mit < 100 Zeilen als 'x'.")
P("  Paare einer Spielerzeile sind stark abhaengig; Intervalle nach Spielen. Konstanten des Produktivmodells (Blowout-Kurve, league_ppm aus 2025-26) sind fuer 2025-26 teils in-sample. Overtime wird nicht modelliert; Ausfaelle unbekannt (A = 'wenn er spielt').")
P("  Die Gruppen der Regel (Meilenstein-Hoehe, Rolle, Spielzahl) und die Parameter wurden an denselben zwei Saisons gesucht (nur mit Kreuz-Anpassung zwischen den Hälften, nicht ueber Saisons hinweg); eine echte Neu-Saison steht aus.")
bc.OUT.with_name("player_calibration3.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))

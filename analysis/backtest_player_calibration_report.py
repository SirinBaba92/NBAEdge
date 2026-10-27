"""
Auswertung zu analysis/backtest_player_calibration.py (Zwischenstaende im Temp-Ordner). NUR LESEND, schreibt nur analysis/reports/player_calibration.txt.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_calibration.py report
Einheit "Zeilen" = Spieler x Meilenstein-Paare (k = 5..40, je Spielerzeile 36 Paare; die Paare einer Spielerzeile und eines Spiels sind NICHT unabhaengig, daher alle Intervalle nach Spielen).
"""
import numpy as np
from scipy.special import expit, logit

import backtest_player_calibration as bc

KS, NK, SEASONS, NB = bc.KS, bc.NK, bc.SEASONS, bc.NB
MIN_ROWS, DEV_MAX = bc.MIN_ROWS, bc.DEV_MAX_PP
L = []
P = L.append

# ------------------------------------------------------------------------------------------------ Daten
parts, var_parts, g_off = [], [], 0
for si, s in enumerate(SEASONS):
    d = np.load(bc.TMP / f"rows_{s}.npz")
    r = {k: d[k] for k in ("gi", "date", "pid", "home", "min", "pts", "emin", "mu0", "epts", "ot", "margin", "ntg", "naive", "n", "n_hist", "n_cur")}
    r["gid"] = r["gi"] + g_off
    r["half"] = (r["gi"] >= int(d["n_games"][0]) // 2).astype(int)
    r["season"] = np.full(len(r["gi"]), si)
    r["ppm_cat"], r["wp_cat"], r["off"], r["mk"] = d["ppm_cat"], d["wp_cat"], d["off"], d["mk"]
    r["n_games"] = int(d["n_games"][0]); r["maxdiff"] = float(d["maxdiff"][0])
    parts.append(r); var_parts.append(np.load(bc.TMP / f"var_{s}.npy"))
    g_off += int(d["n_games"][0])
G = g_off
R = {k: np.concatenate([p[k] for p in parts]) for k in ("gid", "half", "season", "date", "pid", "min", "pts", "emin", "mu0", "epts", "ot", "margin", "ntg", "naive", "n", "n_hist")}
NR = len(R["gid"])
VAR = np.concatenate(var_parts, axis=1)                      # [Variante, Zeile, 36]
VIDX = {n: i for i, n in enumerate(bc.VNAMES)}
PA = VAR[0]
_r = np.random.default_rng(11)
W = np.stack([np.bincount(_r.integers(0, G, G), minlength=G) for _ in range(NB)]).astype(float)

role = np.where(R["mu0"] > 28, 0, np.where(R["mu0"] > 20, 1, 2))
RNAME = ["Starter", "Rotation", "uebrige"]
mcls = np.where(R["emin"] < 15, 0, np.where(R["emin"] < 25, 1, np.where(R["emin"] < 32, 2, 3)))
MNAME = ["unter 15 Min.", "15-25 Min.", "25-32 Min.", "ab 32 Min."]
ref = np.where(np.isfinite(R["naive"]), R["naive"], R["epts"])

# Paare
rp = np.repeat(np.arange(NR), NK)
kp = np.tile(KS, NR)
hit = (R["pts"][rp] >= kp).astype(float)
gid_p = R["gid"][rp]
dk = kp - ref[rp]
kcls = np.where(dk < -3, 0, np.where(dk <= 3, 1, 2))
KCNAME = ["unter dem Spielerschnitt (k < Schnitt - 3)", "um den Schnitt (|k - Schnitt| <= 3)", "ueber dem Schnitt (k > Schnitt + 3)"]
NP = len(rp)
EPS = 1e-6


def pairs(pm):
    return pm.reshape(-1).astype(float)


def cells(mask, b, nb, vals=None):
    key = gid_p[mask] * nb + b[mask]
    cnt = np.bincount(key, minlength=G * nb).reshape(G, nb).astype(float)
    return cnt


def wcells(mask, b, nb, w):
    key = gid_p[mask] * nb + b[mask]
    return np.bincount(key, weights=w[mask], minlength=G * nb).reshape(G, nb)


def pct(a, lo=2.5, hi=97.5):
    return np.percentile(a, lo, axis=0), np.percentile(a, hi, axis=0)


def calib(p, mask, nb=20):
    """Kalibrierung in 5-%-Stufen: Rueckgabe dict mit n, mean_p, rate, dev (PP) und Intervall."""
    b = np.minimum((p * nb).astype(int), nb - 1)
    cnt = cells(mask, b, nb); sp = wcells(mask, b, nb, p); sh = wcells(mask, b, nb, hit)
    n, spt, sht = cnt.sum(0), sp.sum(0), sh.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dev = 100 * (sht - spt) / n
        bs = 100 * (W @ sh - W @ sp) / (W @ cnt)
    lo, hi = pct(bs)
    return {"n": n, "mp": spt / n, "rate": sht / n, "dev": dev, "lo": lo, "hi": hi}


def abw(c):
    n = c["n"]; ok = n > 0
    return float((n[ok] * np.abs(c["dev"][ok])).sum() / n[ok].sum())


def bad_bins(c):
    return [(i, int(c["n"][i]), float(c["dev"][i])) for i in range(len(c["n"])) if c["n"][i] >= MIN_ROWS and abs(c["dev"][i]) > DEV_MAX]


def blab(i, nb=20):
    return f"{100*i//nb:3d}-{100*(i+1)//nb:3d} %"


def print_calib(title, c, nb=20):
    P(f"  {title}")
    P(f"    {'Stufe':10s} {'Zeilen':>9s} {'Ø Modell':>9s} {'Trefferq.':>9s} {'Diff PP [95 %]':>24s}")
    for i in range(nb):
        if c["n"][i] == 0:
            continue
        flag = ""
        if i >= 18 and c["n"][i] < MIN_ROWS:
            flag = "   (ab 90 % mit < 100 Zeilen: nicht aussagekraeftig)"
        elif c["n"][i] < MIN_ROWS:
            flag = "   (< 100 Zeilen)"
        P(f"    {blab(i):10s} {int(c['n'][i]):9d} {100*c['mp'][i]:8.1f}% {100*c['rate'][i]:8.1f}% {c['dev'][i]:+8.2f} [{c['lo'][i]:+.2f}; {c['hi'][i]:+.2f}]{flag}")
    bb = bad_bins(c)
    P(f"    Ø-Abweichung (zeilengewichtet) {abw(c):.2f} PP; Stufen mit >= 100 Zeilen ueber {DEV_MAX:g} PP daneben: " + (", ".join(f"{blab(i)} ({n} Z., {d:+.1f})" for i, n, d in bb) if bb else "keine"))


def fit_logit(n, h, x):
    ok = n > 0
    n, h, x = n[ok], h[ok], x[ok]
    a, b = 0.0, 1.0
    for _ in range(30):
        mu = expit(a + b * x); wv = n * mu * (1 - mu) + 1e-12
        g = np.array([(h - n * mu).sum(), ((h - n * mu) * x).sum()])
        H = np.array([[wv.sum(), (wv * x).sum()], [(wv * x).sum(), (wv * x * x).sum()]])
        st = np.linalg.solve(H, g)
        a += st[0]; b += st[1]
        if np.abs(st).max() < 1e-9:
            break
    return a, b


EDGES = np.linspace(-6.0, 6.0, 49)


def recal(p, mask):
    lg = logit(np.clip(p, EPS, 1 - EPS))
    b = np.clip(np.digitize(lg, EDGES) - 1, 0, len(EDGES) - 2)
    nb = len(EDGES) - 1
    cnt = cells(mask, b, nb); sh = wcells(mask, b, nb, hit); sx = wcells(mask, b, nb, lg)
    def one(c, h, s):
        with np.errstate(invalid="ignore", divide="ignore"):
            x = np.where(c.sum(0) > 0, s.sum(0) / np.maximum(c.sum(0), 1), 0)
        return fit_logit(c.sum(0), h.sum(0), x)
    a0, b0 = one(cnt, sh, sx)
    bs = []
    for w_ in W:
        c = (w_[:, None] * cnt); h = (w_[:, None] * sh); s = (w_[:, None] * sx)
        with np.errstate(invalid="ignore", divide="ignore"):
            x = np.where(c.sum(0) > 0, s.sum(0) / np.maximum(c.sum(0), 1e-12), 0)
        bs.append(fit_logit(c.sum(0), h.sum(0), x))
    bs = np.array(bs)
    return a0, b0, np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])


def group_stat(p, mask):
    """n, Ø Modell, Trefferquote, Diff PP mit Intervall fuer eine Paare-Menge."""
    n_g = np.bincount(gid_p[mask], minlength=G).astype(float)
    sp_g = np.bincount(gid_p[mask], weights=p[mask], minlength=G)
    sh_g = np.bincount(gid_p[mask], weights=hit[mask], minlength=G)
    n = n_g.sum()
    if n == 0:
        return None
    bs = 100 * (W @ sh_g - W @ sp_g) / np.maximum(W @ n_g, 1e-12)
    return int(n), sp_g.sum() / n, sh_g.sum() / n, 100 * (sh_g.sum() - sp_g.sum()) / n, np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def scores(p):
    pc = np.clip(p, EPS, 1 - EPS)
    return float(np.mean((p - hit) ** 2)), float(-np.mean(hit * np.log(pc) + (1 - hit) * np.log(1 - pc)))


# ------------------------------------------------------------------------------------------------ Kopf
nd = len(set(R["date"].tolist()))
P("KALIBRIERUNG UND STREUUNG DER SPIELER-PUNKTE-CHANCEN (Meilensteine P(Punkte >= k)), roh (A), walk-forward, echte Boxscores, ohne Quoten")
P("Skripte analysis/backtest_player_calibration.py (Replay + Varianten) und analysis/backtest_player_calibration_report.py (Auswertung); beide lesen nur. Produktivmodell unveraendert.")
P("")
P("WIEDERVERWENDET: Adapter und Replay aus analysis/backtest_player_markets.py (setup, prepare_games; Spread/Total vor dem Spiel aus dem kausalen Team-Replay) mit analysis/bt_player_adapter.py (Verlauf je Spieler nur vor Spieltag D,")
P("  laufende Saison + Vorsaison, Assertion auf Datum < D), player_games_2023-24/2024-25/2025-26 und die Produktivfunktion engine/player_forecast.forecast_player als Basis A. Die Chancen: gewichtete empirische Verteilung der Punkte pro")
P("  Minute x 9 Minutenquantile, je Punktewert x ein Normalkern der Breite h = 1 + 0,05 x, P(Punkte >= N) = Summe w (1 - Phi((N - 0,5 - x) / h)). Die Bausteine werden nachgerechnet und je Zeile gegen forecast_player geprueft")
P(f"  (groesste Abweichung der Chancen und der erwarteten Punkte: {max(p['maxdiff'] for p in parts):.1e}).")
P("")
P("ZAHLEN: " + f"{len(SEASONS)} Saisons ({', '.join(SEASONS)}), {nd} Spieltage, {G} Spiele, {NR} Spielerzeilen (Prognose vorhanden UND Minuten > 0, alle Teamspiele inkl. Saisonanfang), {NP} Paare Spieler x Meilenstein (k = 5..40).")
P("  'Zeilen' in den Tabellen = Paare. Stufen ab 90 % mit unter 100 Zeilen sind als nicht aussagekraeftig gekennzeichnet. Hälften = erste/zweite Saisonhälfte (nach Datum) beider Saisons, jeweils gepoolt.")
P("  'Spielerschnitt' = Saisonschnitt der Punkte vor dem Spiel (mind. 5 Spiele, sonst Verlauf beider Saisons, sonst erwartete Punkte der Prognose).")
P("")

allm = np.ones(NP, bool)
pA = pairs(PA)

# ------------------------------------------------------------------------------------------------ 1 Kalibrierung
P("1 KALIBRIERUNG (Variante A roh)")
cA = calib(pA, allm)
print_calib("gesamt (alle Meilensteine 5..40)", cA)
P("")
for ci, cn in enumerate(KCNAME):
    print_calib(cn, calib(pA, kcls == ci))
    P("")
P("  Rekalibrierung: logit(Trefferchance) = a + b * logit(Modell-Chance). Ideal a = 0, b = 1 (b < 1: Modell zu selbstsicher; b > 1: zu vorsichtig). Intervall 95 %, Bootstrap nach Spielen.")
P(f"    {'Menge':48s} {'Zeilen':>9s} {'a (Achsenabschnitt)':>26s} {'b (Steigung)':>24s}")
for nm, mk in (("ganze Daten", allm), ("Saison 2024-25", R["season"][rp] == 0), ("Saison 2025-26", R["season"][rp] == 1), (KCNAME[0], kcls == 0), (KCNAME[1], kcls == 1), (KCNAME[2], kcls == 2)):
    a0, b0, ac, bc_ = recal(pA, mk)
    P(f"    {nm:48s} {int(mk.sum()):9d} {a0:+8.3f} [{ac[0]:+.3f}; {ac[1]:+.3f}] {b0:8.3f} [{bc_[0]:.3f}; {bc_[1]:.3f}]")
P("")

# ------------------------------------------------------------------------------------------------ 2 Raender
P("2 ZERLEGUNG DER RAENDER (A): Modell-Chance >= 80 % bzw. < 20 %. Diff = Trefferquote minus Ø-Modell-Chance in PP (negativ = Modell zu hoch). Intervall 95 %, Bootstrap nach Spielen.")
k_band = np.digitize(kp, [11, 16, 21, 26, 31])
KBN = ["k 5-10", "k 11-15", "k 16-20", "k 21-25", "k 26-30", "k 31-40"]
dims = [("Rolle", [(RNAME[i], role[rp] == i) for i in range(3)]),
        ("Minutenklasse (erwartete Minuten)", [(MNAME[i], mcls[rp] == i) for i in range(4)]),
        ("Meilenstein-Hoehe", [(KBN[i], k_band == i) for i in range(6)]),
        ("Saisonphase", [("erste 15 Teamspiele", R["ntg"][rp] < 15), ("ab dem 16. Teamspiel", R["ntg"][rp] >= 15)]),
        ("Verlaengerung", [("mit Verlaengerung", R["ot"][rp] == 1), ("ohne Verlaengerung", R["ot"][rp] == 0)]),
        ("Endstand", [("Blowout (Differenz >= 20)", R["margin"][rp] >= 20), ("knapp (Differenz < 20)", R["margin"][rp] < 20)])]
for side, sm in (("Modell-Chance >= 80 %", pA >= 0.8), ("Modell-Chance < 20 %", pA < 0.2)):
    P(f"  {side}")
    gs = group_stat(pA, sm)
    P(f"    {'Gruppe':36s} {'Zeilen':>9s} {'Ø Modell':>9s} {'Trefferq.':>9s} {'Diff PP [95 %]':>24s}")
    P(f"    {'alle':36s} {gs[0]:9d} {100*gs[1]:8.1f}% {100*gs[2]:8.1f}% {gs[3]:+8.2f} [{gs[4]:+.2f}; {gs[5]:+.2f}]")
    for dn, items in dims:
        P(f"    -- {dn}")
        for nm, mk in items:
            gs = group_stat(pA, sm & mk)
            if gs is None:
                P(f"    {nm:36s} {0:9d}"); continue
            P(f"    {nm:36s} {gs[0]:9d} {100*gs[1]:8.1f}% {100*gs[2]:8.1f}% {gs[3]:+8.2f} [{gs[4]:+.2f}; {gs[5]:+.2f}]" + ("   (< 100 Zeilen)" if gs[0] < MIN_ROWS else ""))
    P("")

# ------------------------------------------------------------------------------------------------ 3 Streuung
P("3 STREUUNG: echte Streuung der Punkte (Ist minus Prognose-Mittel) gegen die Streuung der Modell-Verteilung (A)")
mvar = np.zeros(NR)
for si, pt in enumerate(parts):
    base = int(np.sum([len(q["gid"]) for q in parts[:si]]))
    for j in range(len(pt["gid"])):
        a, b = pt["off"][j], pt["off"][j + 1]
        x, w = bc.xw(pt["ppm_cat"][a:b], pt["wp_cat"][a:b], pt["mk"][j])
        mu = (w * x).sum()
        mvar[base + j] = (w * ((x - mu) ** 2 + (1.0 + 0.05 * x) ** 2)).sum()
err = R["pts"] - R["epts"]
rowG = R["gid"]


def sums(mask):
    c = [np.bincount(rowG[mask], weights=v[mask], minlength=G) for v in (np.ones(NR), err, err ** 2, mvar, R["epts"])]
    return c


def ratio_stat(mask):
    n, s1, s2, sv, se = sums(mask)
    def f(n_, s1_, s2_, sv_):
        return np.sqrt(np.maximum(s2_ / n_ - (s1_ / n_) ** 2, 0) / (sv_ / n_))
    pt = float(f(n.sum(), s1.sum(), s2.sum(), sv.sum()))
    bs = f(W @ n, W @ s1, W @ s2, W @ sv)
    real = float(np.sqrt(max(s2.sum() / n.sum() - (s1.sum() / n.sum()) ** 2, 0)))
    return int(n.sum()), real, float(np.sqrt(sv.sum() / n.sum())), pt, np.percentile(bs, 2.5), np.percentile(bs, 97.5), float(se.sum() / n.sum()), float(s1.sum() / n.sum())


P("  Echte Streuung = Standardabweichung von (Ist - Prognose-Mittel) je Gruppe; Modell-Streuung = Wurzel aus der mittleren Varianz der Modell-Verteilung (Streuung der Punktewerte x plus Kernbreite h^2). Verhaeltnis > 1: Modell zu schmal.")
P(f"  {'Gruppe':34s} {'Zeilen':>7s} {'Ø Prognose':>10s} {'Bias':>7s} {'echte SD':>9s} {'Modell-SD':>10s} {'Verhaeltnis echt/Modell [95 %]':>34s}")


def ratio_line(nm, mask):
    if mask.sum() == 0:
        return
    n, real, mod, rt, lo, hi, mean_p, bias = ratio_stat(mask)
    P(f"  {nm:34s} {n:7d} {mean_p:10.1f} {bias:+7.2f} {real:9.2f} {mod:10.2f} {rt:10.3f} [{lo:.3f}; {hi:.3f}]" + ("   (< 100 Zeilen)" if n < MIN_ROWS else ""))


ratio_line("alle", np.ones(NR, bool))
for ri in range(3):
    ratio_line(f"Rolle {RNAME[ri]}", role == ri)
for mi in range(4):
    ratio_line(f"Minuten {MNAME[mi]}", mcls == mi)
P("  Rolle x Minutenklasse:")
for ri in range(3):
    for mi in range(4):
        ratio_line(f"  {RNAME[ri]} / {MNAME[mi]}", (role == ri) & (mcls == mi))
P("")
P("  Mittelwert-Unsicherheit: Streuung der Prognosefehler nach der Zahl der bisherigen Spiele des Spielers (Spiele mit mind. 8 Minuten im Verlauf, beide Saisons).")
P("  Ueberschuss = echte Varianz minus Modell-Varianz; implizites c = sqrt(Ueberschuss) / Ø-Prognose * sqrt(Ø n) (V2 nimmt tau_n = c / sqrt(n) als relative Unsicherheit des Mittelwerts an).")
NBINS = [(1, 9), (10, 19), (20, 39), (40, 79), (80, 999)]
P(f"  {'Gruppe':34s} {'Zeilen':>7s} {'Ø Prognose':>10s} {'echte SD':>9s} {'Modell-SD':>10s} {'Verhaeltnis [95 %]':>24s} {'SD/Prognose':>12s} {'impl. c':>8s}")
for gname, gm in (("alle Spieler", np.ones(NR, bool)), ("Starter", role == 0), ("Rotation", role == 1), ("uebrige", role == 2)):
    for lo_, hi_ in NBINS:
        mk = gm & (R["n"] >= lo_) & (R["n"] <= hi_)
        if mk.sum() == 0:
            continue
        n, real, mod, rt, lo, hi, mean_p, bias = ratio_stat(mk)
        exc = max(real ** 2 - mod ** 2, 0)
        nbar = float(R["n"][mk].mean())
        impl = np.sqrt(exc) / mean_p * np.sqrt(nbar) if mean_p > 0 else np.nan
        P(f"  {gname + ', n=' + str(lo_) + ('-' + str(hi_) if hi_ < 999 else '+'):34s} {n:7d} {mean_p:10.1f} {real:9.2f} {mod:10.2f} {rt:8.3f} [{lo:.3f}; {hi:.3f}] {real/mean_p:12.3f} {impl:8.2f}" + ("   (< 100 Zeilen)" if n < MIN_ROWS else ""))
    P("")

# ------------------------------------------------------------------------------------------------ 4 Varianten
P("4 VARIANTEN (nur im Replay; Produktivmodell unveraendert). V1: Kern h = 2,0 x (1 + 0,05 x) [c = 2,0 als Faktor auf den Produktivkern: ein fester Wert h = 2 waere bei hohen x schmaler als heute].")
P("  V2: Mittelwert-Unsicherheit, h^2 = (1+0,05x)^2 + (c/sqrt(n) * x)^2 mit n = Spiele des Spielers; V3: V1 + V2; V4: negative Binomialverteilung (Mittel = erwartete Punkte, Varianz = mu + mu^2 / r).")
P("  Die Parameter c (V2, V3) und r (V4) werden auf einer Haelfte durch kleinsten Log-Loss ueber alle Paare der Haelfte eingestellt und auf der anderen angewandt, und umgekehrt (Kreuz-Anpassung). Alle Zahlen unten fuer V2-V4 sind")
P("  daher 'ausserhalb der Stichprobe' (jede Zeile mit den Parametern der jeweils anderen Haelfte). A und V1 haben keinen freien Parameter.")
half_p = R["half"][rp]
ll = {}
for nm in bc.VNAMES:
    pm = np.clip(pairs(VAR[VIDX[nm]]), EPS, 1 - EPS)
    l = -(hit * np.log(pm) + (1 - hit) * np.log(1 - pm))
    ll[nm] = [float(l[half_p == h].mean()) for h in (0, 1)]
FAM = {"V2": [n for n in bc.VNAMES if n.startswith("V2")], "V3": [n for n in bc.VNAMES if n.startswith("V3")], "V4": [n for n in bc.VNAMES if n.startswith("V4")]}
best = {}                                   # (Familie, Lernhaelfte) -> Name
for f, names in FAM.items():
    for lh in (0, 1):
        best[(f, lh)] = min(names, key=lambda n: ll[n][lh])
P("  Gewaehlte Parameter (kleinster Log-Loss auf der Lernhaelfte):")
for f in FAM:
    P(f"    {f}: gelernt auf Haelfte 1 -> {best[(f, 0)]}; gelernt auf Haelfte 2 -> {best[(f, 1)]}   (Log-Loss je Parameter, Haelfte 1 / 2: " + ", ".join(f"{n.split(' ')[1]}: {ll[n][0]:.4f}/{ll[n][1]:.4f}" for n in FAM[f]) + ")")
P(f"    A: Log-Loss Haelfte 1 / 2: {ll['A'][0]:.4f} / {ll['A'][1]:.4f}; V1: {ll['V1'][0]:.4f} / {ll['V1'][1]:.4f}")
CF = {"A": pA, "V1": pairs(VAR[VIDX["V1"]])}
for f in FAM:
    # Zeilen der Haelfte h bekommen die Parameter, die auf der anderen Haelfte gelernt wurden
    CF[f] = np.where(half_p == 1, pairs(VAR[VIDX[best[(f, 0)]]]), pairs(VAR[VIDX[best[(f, 1)]]]))
VLABEL = {"A": "A roh", "V1": "V1 Kern c = 2,0", "V2": "V2 Mittelwert-Unsicherheit", "V3": "V3 = V1 + V2", "V4": "V4 negative Binomial"}
P("")
P("  4a Kalibrierung gesamt je Variante")
P(f"    {'Variante':28s} {'Ø-Abw. PP':>10s} {'Stufen >= 100 Z. ueber 6 PP':>30s} {'Brier':>9s} {'Log-Loss':>9s} {'Rekal. a':>9s} {'Rekal. b':>9s}")
CAL = {}
for v, pv in CF.items():
    c = calib(pv, allm); CAL[v] = c
    br, lg_ = scores(pv)
    a0, b0, _, _ = recal(pv, allm)
    P(f"    {VLABEL[v]:28s} {abw(c):10.2f} {len(bad_bins(c)):30d} {br:9.5f} {lg_:9.5f} {a0:+9.3f} {b0:9.3f}")
P("  4b Randstufen einzeln (Diff PP = Trefferquote minus Ø-Modell; Zeilen in Klammern; ab 90 % mit < 100 Zeilen: nicht aussagekraeftig = 'x')")
edge_idx = [0, 1, 2, 3, 16, 17, 18, 19]
P(f"    {'Variante':28s} " + " ".join(f"{blab(i):>17s}" for i in edge_idx))
for v, c in CAL.items():
    cells_ = []
    for i in edge_idx:
        n = int(c["n"][i])
        mark = "x" if (i >= 18 and n < MIN_ROWS) else ("*" if n < MIN_ROWS else " ")
        cells_.append(f"{c['dev'][i]:+6.1f} ({n:7d}){mark}" if n else "-")
    P(f"    {VLABEL[v]:28s} " + " ".join(f"{s:>17s}" for s in cells_))
P("    (* = unter 100 Zeilen)")
P("  4c Stufen mit >= 100 Zeilen ueber 6 PP daneben")
for v, c in CAL.items():
    bb = bad_bins(c)
    P(f"    {VLABEL[v]:28s} " + (", ".join(f"{blab(i)} ({n} Z., {d:+.1f})" for i, n, d in bb) if bb else "keine"))
P("")

# ------------------------------------------------------------------------------------------------ 5 Auswahl
P("5 AUSWAHL NACH REGEL: Eine Variante zaehlt nur, wenn sie auf BEIDEN Pruefhaelften (a) die Ø-Abweichung gegenueber A verbessert und (b) keine Stufe mit >= 100 Zeilen ueber 6 PP daneben liegt.")
verdict = {v: [] for v in CF}
for th_, lh_ in ((1, 0), (0, 1)):
    mk = half_p == th_
    P(f"  Pruefhaelfte {th_ + 1} (Parameter gelernt auf Haelfte {lh_ + 1}); {int(mk.sum())} Paare")
    cA_ = calib(pA, mk); abwA = abw(cA_)
    for v, pv in CF.items():
        c = calib(pv, mk); bb = bad_bins(c); a_ = abw(c)
        better = a_ < abwA
        passed = better and not bb if v != "A" else not bb
        if v != "A":
            verdict[v].append(passed)
        br, lg_ = scores_half = scores(pv) if False else (None, None)
        P(f"    {VLABEL[v]:28s} Ø-Abw. {a_:5.2f} PP (A: {abwA:5.2f}) -> {'besser' if better else 'nicht besser'}; Stufen ueber 6 PP: " + (", ".join(f"{blab(i)} ({n} Z., {d:+.1f})" for i, n, d in bb) if bb else "keine") + ("" if v == "A" else f"  => {'erfuellt' if passed else 'verfehlt'}"))
P("  Ergebnis:")
for v in CF:
    if v == "A":
        continue
    P(f"    {VLABEL[v]:28s} {'ZAEHLT (beide Pruefhaelften erfuellt)' if all(verdict[v]) else 'zaehlt NICHT'}   (Haelfte 2: {'ja' if verdict[v][0] else 'nein'}, Haelfte 1: {'ja' if verdict[v][1] else 'nein'})")
P("")

# ------------------------------------------------------------------------------------------------ 6 Ehrlichkeit
P("6 EHRLICHE ZAHLEN")
P(f"  {len(SEASONS)} Saisons, {nd} Spieltage, {G} Spiele, {NR} Spielerzeilen, {NP} Paare. Zeilen je Stufe stehen in den Tabellen 1, 4a-4c; Stufen ab 90 % mit unter 100 Zeilen sind markiert.")
P("  Die Paare einer Spielerzeile (36 Meilensteine) sind stark abhaengig; die Intervalle (Bootstrap nach Spielen) beruecksichtigen das. Konstanten des Produktivmodells (Blowout-Kurve, league_ppm aus 2025-26) sind fuer 2025-26 teils in-sample.")
P("  Overtime wird vom Modell nicht modelliert; Ausfaelle von Mitspielern sind unbekannt (A ist die rohe Prognose 'wenn er spielt', bewertet nur Spieler mit Minuten > 0).")
bc.OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))

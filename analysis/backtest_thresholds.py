"""
Schwellwert-Test: fuer jede Modell-Chance-Schwelle (50 % bis 95 %, 5-%-Schritte) zeigen, wie viele Tipps es gegeben haette und wie viele richtig waren. NUR LESEND, Produktivmodell unveraendert.
Schreibt nur analysis/reports/threshold_test.txt.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_thresholds.py [--selftest]

Quellen: Team-Maerkte wie analysis/backtest_winner.py / backtest_spread.py / backtest_total.py / backtest_team_total.py (Replay analysis/replica_tunable.run mit den Produktivparametern, walk-forward ab 2015,
Auswertung Regular Season 2025-26, reines Modell ohne Markt-Mischung, Sigmas aus engine/line_probabilities). Spielerpunkte: Zwischenstaende von analysis/backtest_player_calibration.py (run) fuer 2024-25 und 2025-26, Variante A roh.
Tipps (nur echte Ergebnisse, keine Quoten; Push = Ergebnis genau auf der Linie, zaehlt weder richtig noch falsch):
 Sieger: der Favorit des Modells (Heim bei Spread 0). Chance = max(p, 1 - p) der Siegchance Heim (begrenzt 3-97 %, wie die App).
 Spread: je Linie L = mu + k (k = -5..+5, mu = Modell-Spread auf 0,1 gerundet; k = 0 ist die Hauptlinie = Modell-Wert selbst, dort 50:50 und die Favoriten-Seite gilt als Tipp) die Seite mit der hoeheren Deckungs-Chance
   (P(Marge > L) fuer Heim, sonst Gast). 'Favorit-Seite' = getippte Seite ist das Modell-Favoritenteam, 'Aussenseiter-Seite' = getippte Seite ist der Modell-Aussenseiter (nimmt Punkte).
 Total: nur Over, Linie L = mu - k (k = 0..5, k = 0 ist der Modell-Wert selbst). Team Total: nur Over, L = mu_Team - k (k = 0..5), Heim und Gast getrennt.
 Spielerpunkte: Over (Punkte >= k) je Meilenstein k = 5..40, 4 Gruppen nach vor dem Spiel bekannter Rolle (Basis-Minuten > 28 Starter, > 20 Rotation, sonst uebrige) und Zahl der bisherigen Spiele.
Mehrere Linien eines Spiels sind korreliert: alle Intervalle (95 %) Bootstrap NACH SPIELEN (1000 Ziehungen). Tipp-Reihenfolge fuer Serien: nach Datum, Spiel, Linie; Pushes ueberspringen die Serie (weder verlaengern noch beenden).
"""
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.special import ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

OUT = HERE / "reports" / "threshold_test.txt"
THR = [round(0.50 + 0.05 * i, 2) for i in range(10)]
NB = 1000
MIN_TIPS = 100
BE15 = 1 / 1.5                                   # Break-even-Trefferquote einer Quote von 1,50
GOAL = BE15 + 0.03
FIRST_N = 15
L = []
P = L.append


# ------------------------------------------------------------------------------------------------ Kern
def run_lengths(loss):
    """Laengen der Serien True in Folge."""
    if len(loss) == 0:
        return np.array([], int)
    x = np.concatenate([[0], loss.astype(int), [0]])
    d = np.diff(x)
    return np.where(d == -1)[0] - np.where(d == 1)[0]


class Tips:
    """p: Modell-Chance, res: 1 richtig / 0 falsch / -1 Push, gid: Spiel (0..G-1) fuer den Bootstrap, in Tipp-Reihenfolge sortiert. half/first: Teilmengen (0/1 bzw. bool)."""

    def __init__(self, p, res, gid, half, first, G, W):
        self.p, self.res, self.gid, self.half, self.first, self.G, self.W = np.asarray(p, float), np.asarray(res, int), np.asarray(gid, int), np.asarray(half, int), np.asarray(first, bool), G, W

    def sub(self, mask):
        return Tips(self.p[mask], self.res[mask], self.gid[mask], self.half[mask], self.first[mask], self.G, self.W)

    def stat(self, mask):
        """(richtig, falsch, push, Trefferquote, lo, hi) der Tipps in mask."""
        G, W = self.G, self.W
        g = self.gid[mask]; r = self.res[mask]
        w = np.bincount(g[r == 1], minlength=G).astype(float)
        l_ = np.bincount(g[r == 0], minlength=G).astype(float)
        nw, nl, npu = int(w.sum()), int(l_.sum()), int((r == -1).sum())
        if nw + nl == 0:
            return nw, nl, npu, np.nan, np.nan, np.nan
        den = W @ (w + l_)
        with np.errstate(invalid="ignore", divide="ignore"):
            bs = (W @ w) / den
        return nw, nl, npu, nw / (nw + nl), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))

    def streaks(self, mask):
        """(laengste Verlustserie, Ø Serie, laengste Spiel-Serie) ohne Pushes. Spiel-Serie: Spiele mit mindestens einem Tipp, in denen KEIN Tipp richtig war."""
        r = self.res[mask]; g = self.gid[mask]
        keep = r >= 0
        r, g = r[keep], g[keep]
        rl = run_lengths(r == 0)
        longest = int(rl.max()) if len(rl) else 0
        mean = float(rl.mean()) if len(rl) else 0.0
        if len(g) == 0:
            return longest, mean, 0
        order = np.unique(g, return_index=True)
        games = order[0][np.argsort(order[1])]                        # Spiele in Tipp-Reihenfolge
        won = {int(x) for x in g[r == 1]}
        lost_game = np.array([int(x) not in won for x in games])
        rg = run_lengths(lost_game)
        return longest, mean, int(rg.max()) if len(rg) else 0


def pc(x, d=1):
    return "   -  " if not np.isfinite(x) else f"{100 * x:{5 + d - 1}.{d}f}"


def main_table(name, T):
    P(f"  {name}")
    P(f"    {'Schwelle':>8s} {'Tipps':>7s} {'richtig':>8s} {'falsch':>7s} {'Push':>5s} {'Trefferquote % [95 %]':>24s} {'Ø Modell':>9s} {'Ø Modell richtige':>18s} {'Diff PP':>8s} {'BE-Quote':>9s} {'BE vorsicht.':>12s} {'Serie max':>9s} {'Ø Serie':>8s} {'Spiel-Serie':>11s}")
    for t in THR:
        m = T.p >= t - 1e-9
        nw, nl, npu, hr, lo, hi = T.stat(m)
        n = nw + nl
        if n == 0:
            P(f"    {int(100 * t):7d}% {int(m.sum()):7d}   (keine Tipps)")
            continue
        mp = T.p[m & (T.res >= 0)]
        mp_w = T.p[m & (T.res == 1)]
        sm, sa, sg = T.streaks(m)
        flag = f"   (< {MIN_TIPS} Tipps: nicht aussagekraeftig)" if n < MIN_TIPS else ""
        P(f"    {int(100 * t):7d}% {int(m.sum()):7d} {nw:8d} {nl:7d} {npu:5d} {pc(hr)} [{pc(lo)};{pc(hi)}] {pc(mp.mean()):>9s} {pc(mp_w.mean()) if nw else '   -  ':>18s} {100 * (hr - mp.mean()):+8.1f} {1 / hr:9.2f} {1 / lo if lo > 0 else float('inf'):12.2f} {sm:9d} {sa:8.1f} {sg:11d}{flag}")
    P("")


def split_table(name, T):
    P(f"  {name}: Tipps / Trefferquote % [95 %] je Teilmenge")
    P(f"    {'Schwelle':>8s} {'Hälfte 1':>30s} {'Hälfte 2':>30s} {'erste 15':>30s} {'Rest':>30s}")
    for t in THR:
        m = T.p >= t - 1e-9
        cells = []
        for sm in (T.half == 0, T.half == 1, T.first, ~T.first):
            nw, nl, npu, hr, lo, hi = T.stat(m & sm)
            n = nw + nl
            cells.append("-" if n == 0 else f"{n:6d} {pc(hr)} [{pc(lo)};{pc(hi)}]{'*' if n < MIN_TIPS else ' '}")
        P(f"    {int(100 * t):7d}% " + " ".join(f"{c:>30s}" for c in cells))
    P("    (* = unter 100 Tipps: nicht aussagekraeftig)")
    P("")


def summary(name, T, user_thr=None, user_note=""):
    """Zusammenfassung: ab welcher Schwelle liegt die Trefferquote in beiden Haelften >= Break-even(1,50) + 3 PP, durchgehend fuer alle hoeheren Schwellen mit >= 100 Tipps je Haelfte."""
    rows = []
    for t in THR:
        m = T.p >= t - 1e-9
        s1 = T.stat(m & (T.half == 0)); s2 = T.stat(m & (T.half == 1)); sa = T.stat(m)
        n1, n2 = s1[0] + s1[1], s2[0] + s2[1]
        ok = n1 >= MIN_TIPS and n2 >= MIN_TIPS and s1[3] >= GOAL and s2[3] >= GOAL
        valid = n1 >= MIN_TIPS and n2 >= MIN_TIPS
        rows.append((t, n1, n2, s1[3], s2[3], ok, valid, sa))
    star = None
    for i, r in enumerate(rows):
        if r[5] and all(x[5] for x in rows[i:] if x[6]):
            star = r[0]; break
    P(f"  {name}")
    P(f"    {'Schwelle':>8s} {'Tipps H1':>9s} {'Tipps H2':>9s} {'Quote H1':>9s} {'Quote H2':>9s} {'beide >= ' + format(100 * GOAL, '.1f') + ' %':>16s}")
    for t, n1, n2, h1, h2, ok, valid, sa in rows:
        P(f"    {int(100 * t):7d}% {n1:9d} {n2:9d} {pc(h1):>9s} {pc(h2):>9s} {('JA' if ok else 'nein') if valid else 'unter 100 Tipps':>16s}")
    P(f"    => durchgehend erfuellt ab: {('%d %%' % int(round(100 * star))) if star is not None else 'keine Schwelle (mit >= 100 Tipps je Haelfte)'}")
    allv = [(r[0], r[7]) for r in rows if r[6] and r[7][3] - 0 >= 0 and r[7][4] >= BE15]
    if allv:
        P(f"    Zusatz: kleinste Schwelle, deren GANZE Stichprobe mit unterer Intervallgrenze ueber dem Break-even von Quote 1,50 ({100 * BE15:.1f} %) liegt: {int(round(100 * allv[0][0]))} %")
    else:
        P(f"    Zusatz: keine Schwelle, deren untere Intervallgrenze ueber dem Break-even von Quote 1,50 ({100 * BE15:.1f} %) liegt (mit >= 100 Tipps je Haelfte).")
    if user_thr is not None:
        for ut, label in user_thr:
            m = T.p >= ut - 1e-9
            sub = T.first if "erste" in label else None
            msub = m & (T.first if "erste" in label else (~T.first if "Rest" in label else np.ones(len(m), bool)))
            s1 = T.stat(msub & (T.half == 0)); s2 = T.stat(msub & (T.half == 1)); sa = T.stat(msub)
            n1, n2, na = s1[0] + s1[1], s2[0] + s2[1], sa[0] + sa[1]
            P(f"    Dein Vorschlag {label} ab {int(100 * ut)} %: Tipps {na} (H1 {n1}, H2 {n2}); Trefferquote {pc(sa[3])} % [{pc(sa[4])};{pc(sa[5])}], H1 {pc(s1[3])} %, H2 {pc(s2[3])} %; Break-even-Quote {1 / sa[3] if sa[3] > 0 else float('inf'):.2f}"
              + ("   (unter 100 Tipps: nicht aussagekraeftig)" if min(n1, n2) < MIN_TIPS else "") + f"; Ziel {100 * GOAL:.1f} % in beiden Haelften: {'erfuellt' if (n1 >= MIN_TIPS and n2 >= MIN_TIPS and s1[3] >= GOAL and s2[3] >= GOAL) else 'NICHT erfuellt'}")
    P("")
    return star, rows


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    check("Serien: [1,1,0,1,1,1] -> 3 und 2", list(run_lengths(np.array([1, 1, 0, 1, 1, 1], bool))) == [2, 3])
    G = 4
    W = np.ones((5, G))
    T = Tips([0.6, 0.7, 0.8, 0.9, 0.55, 0.65], [1, 0, -1, 0, 0, 1], [0, 0, 1, 1, 2, 3], [0, 0, 0, 1, 1, 1], [True, False, False, False, True, False], G, W)
    s = T.stat(T.p >= 0.6)
    check("stat: 0.6/0.7/0.8/0.9/0.65 -> richtig 2, falsch 2, Push 1", (s[0], s[1], s[2]) == (2, 2, 1), s)
    sm, sa, sg = T.streaks(T.p >= 0.5)
    check("Serien: richtig,falsch,(Push uebersprungen),falsch,falsch,richtig -> eine Serie der Laenge 3", sm == 3 and abs(sa - 3.0) < 1e-12, (sm, sa))
    check("Spiel-Serie: Spiel 0 richtig, 1 falsch, 2 falsch, 3 richtig -> 2", sg == 2, sg)
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from bt_common import load_games
    import replica_tunable as rt
    import backtest_player_calibration as bc
    from config.settings import ELO_TO_SPREAD_FACTOR
    from engine import line_probabilities as lp

    PRODUCTION = dict(K=20.0, hca=100.0, mov="cur", total_alpha=0.1)
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **PRODUCTION)
    sel = np.where((rows["season"] == 2025) & (rows["post"] == 0))[0]
    n = len(sel)
    mu_s = np.round(rows["diff"][sel] / ELO_TO_SPREAD_FACTOR, 1)           # Modell-Spread (positiv = Heim staerker)
    mu_t = np.round(rows["total_pred"][sel], 1)
    mg, tot = rows["margin"][sel], rows["total"][sel]
    gh, ga = rows["gp_h"][sel], rows["gp_a"][sel]
    first_g = (gh < FIRST_N) & (ga < FIRST_N)
    half_g = (np.arange(n) >= n // 2).astype(int)
    rng = np.random.default_rng(2026)
    Wt = np.stack([np.bincount(rng.integers(0, n, n), minlength=n) for _ in range(NB)]).astype(float)
    SS, ST, SQ = lp.SPREAD_SIGMA, lp.TOTAL_SIGMA, lp.TEAM_TOTAL_SIGMA

    def build(items, meta=None):
        """items: Liste (game_index, order, p, res, group) -> dict group -> Tips (nach order sortiert)."""
        gi = np.array([x[0] for x in items]); od = np.array([x[1] for x in items]); pp = np.array([x[2] for x in items]); rs = np.array([x[3] for x in items]); gr = np.array([x[4] for x in items])
        o = np.argsort(od, kind="stable")
        gi, pp, rs, gr = gi[o], pp[o], rs[o], gr[o]
        out = {}
        for g_ in sorted(set(gr.tolist())):
            m = gr == g_
            out[g_] = Tips(pp[m], rs[m], gi[m], half_g[gi[m]], first_g[gi[m]], n, Wt)
        out["alle"] = Tips(pp, rs, gi, half_g[gi], first_g[gi], n, Wt)
        return out

    markets = {}
    # Sieger
    p_home = np.array([lp.win_prob_home(float(x)) for x in mu_s])
    fav_home = p_home >= 0.5
    q = np.where(fav_home, p_home, 1 - p_home)
    win = np.where(fav_home, mg > 0, mg < 0).astype(int)
    items = [(i, i, q[i], win[i], "Favorit Heim" if fav_home[i] else "Favorit Gast") for i in range(n)]
    markets["Sieger (Favorit des Modells)"] = build(items)
    # Spread
    items = []
    for i in range(n):
        for j, k in enumerate(range(-5, 6)):
            Lr = mu_s[i] + k
            ph = 1.0 - ndtr((Lr - mu_s[i]) / SS)
            if k == 0:
                tip_home = mu_s[i] >= 0
            else:
                tip_home = ph > 0.5
            q_ = ph if tip_home else 1 - ph
            if mg[i] == Lr:
                r_ = -1
            else:
                r_ = int((mg[i] > Lr) == tip_home)
            if mu_s[i] == 0:
                grp = "gleich stark (Spread 0)"
            else:
                fav_is_home = mu_s[i] > 0
                grp = "Favorit-Seite" if tip_home == fav_is_home else "Aussenseiter-Seite"
            items.append((i, i * 16 + j, q_, r_, grp))
    markets["Spread (Seite mit der hoeheren Deckungs-Chance, Linien mu-5 .. mu+5)"] = build(items)
    # Total
    items = []
    for i in range(n):
        for j, k in enumerate(range(0, 6)):
            Lr = mu_t[i] - k
            p_ = 1.0 - ndtr((Lr - mu_t[i]) / ST)
            r_ = -1 if tot[i] == Lr else int(tot[i] > Lr)
            items.append((i, i * 16 + j, p_, r_, "Over"))
    markets["Total (nur Over, Linien mu .. mu-5)"] = build(items)
    # Team Total
    pts_h, pts_a = (tot + mg) / 2, (tot - mg) / 2
    items = []
    for i in range(n):
        for side, mu_, pts_ in (("Heim", (mu_t[i] + mu_s[i]) / 2, pts_h[i]), ("Gast", (mu_t[i] - mu_s[i]) / 2, pts_a[i])):
            mu_ = round(float(mu_), 1)
            for j, k in enumerate(range(0, 6)):
                Lr = mu_ - k
                p_ = 1.0 - ndtr((Lr - mu_) / SQ)
                r_ = -1 if pts_ == Lr else int(pts_ > Lr)
                items.append((i, i * 16 + j, p_, r_, side))
    markets["Team Total (nur Over, Linien mu .. mu-5)"] = build(items)

    # Spielerpunkte
    PL = {}
    parts, g_off = [], 0
    for s in bc.SEASONS:
        d = np.load(bc.TMP / f"rows_{s}.npz")
        pa = np.load(bc.TMP / f"var_{s}.npy")[0]
        ng = int(d["n_games"][0])
        parts.append({"gid": d["gi"] + g_off, "half": (d["gi"] >= ng // 2).astype(int), "pts": d["pts"], "mu0": d["mu0"], "n_hist": d["n_hist"], "pa": pa})
        g_off += ng
    Gp = g_off
    gid = np.concatenate([q_["gid"] for q_ in parts]); half_r = np.concatenate([q_["half"] for q_ in parts]); pts_r = np.concatenate([q_["pts"] for q_ in parts])
    mu0 = np.concatenate([q_["mu0"] for q_ in parts]); nh = np.concatenate([q_["n_hist"] for q_ in parts]); PAm = np.concatenate([q_["pa"] for q_ in parts], axis=0)
    NR = len(gid)
    KSP = np.arange(5, 41)
    NKp = len(KSP)
    rng = np.random.default_rng(2027)
    Wp = np.stack([np.bincount(rng.integers(0, Gp, Gp), minlength=Gp) for _ in range(NB)]).astype(float)
    role = np.where(mu0 > 28, 0, np.where(mu0 > 20, 1, 2))
    grp_row = np.where((role == 0) & (nh >= 10), 0, np.where(role == 0, 1, np.where(role == 1, 2, 3)))
    GN = ["Starter mit >= 10 bisherigen Spielen", "Starter mit < 10 bisherigen Spielen", "Rotation", "uebrige"]
    rp = np.repeat(np.arange(NR), NKp)
    kp = np.tile(KSP, NR)
    hit_p = (pts_r[rp] >= kp).astype(int)
    pp = PAm.reshape(-1).astype(float)
    for gi_, gname in enumerate(GN):
        m = grp_row[rp] == gi_
        PL[gname] = Tips(pp[m], hit_p[m], gid[rp][m], half_r[rp][m], (nh < 10)[rp][m], Gp, Wp)
    PL["alle Spieler"] = Tips(pp, hit_p, gid[rp], half_r[rp], (nh < 10)[rp], Gp, Wp)

    nd = len(set(np.concatenate([q_["gid"] for q_ in parts]).tolist()))
    P("SCHWELLWERT-TEST: WIE VIELE TIPPS HAETTE ES JE MODELL-CHANCE-SCHWELLE GEGEBEN UND WIE VIELE WAREN RICHTIG?")
    P("Skript analysis/backtest_thresholds.py (liest nur; Produktivmodell unveraendert). Reines Modell ohne Markt-Mischung, walk-forward, nur echte Ergebnisse, keine Quoten.")
    P(f"Team-Maerkte: Regular Season 2025-26, {n} Spiele (Replay der Produktiv-ELO-Engine ab 2015). Spielerpunkte: 2024-25 und 2025-26, {Gp} Spiele, {NR} Spielerzeilen, {NR * NKp} Tipps (Over je Meilenstein k = 5..40, Variante A roh).")
    P("TIPPS JE MARKT (Definition):")
    P("  Sieger: der Favorit des Modells (Chance = max(p, 1-p) der Siegchance Heim, wie in der App begrenzt auf 3-97 %). Spread: je Linie L = mu + k (k = -5..+5; k = 0 ist die Hauptlinie = Modell-Spread selbst, dort 50:50, Favoriten-Seite) die Seite mit der")
    P("  hoeheren Deckungs-Chance; 'Favorit-Seite' und 'Aussenseiter-Seite' getrennt. Total / Team Total: nur Over, an der Hauptlinie (Modell-Wert selbst) und 1 bis 5 Punkte darunter; Team Total Heim und Gast getrennt. Spielerpunkte: Over je Meilenstein k = 5..40.")
    P("  Ein Spiel liefert bei Spread/Total/Team Total mehrere Tipps (eine je Linie). Diese Tipps sind stark korreliert (gleiches Spielergebnis): die Intervalle laufen nach Spielen, und die Serien stehen als Tipp-Serie (alle Tipps nacheinander) und als Spiel-Serie.")
    P("SPALTEN: Schwelle = Modell-Chance mindestens so hoch. Trefferquote = richtig / (richtig + falsch) ohne Push. Ø Modell = mittlere Modell-Chance der Tipps ohne Push; Diff = Trefferquote minus Ø Modell (positiv = Modell zu vorsichtig).")
    P(f"  Break-even-Quote = 1 / Trefferquote (ab dieser Quote lohnt sich das Tippen); 'vorsichtig' = 1 / untere Intervallgrenze. Ziel der Zusammenfassung: Trefferquote in BEIDEN Haelften mindestens {100 * GOAL:.1f} % (= Break-even einer Quote von 1,50 ({100 * BE15:.1f} %) plus 3 PP).")
    P("  Serie max / Ø Serie = laengste bzw. mittlere Serie falscher Tipps in Folge (nach Datum, Pushes uebersprungen); Spiel-Serie = laengste Folge von Spielen, in denen KEIN Tipp richtig war. Teilmengen: Haelfte 1/2 = chronologisch (bei Spielerpunkten je Saison),")
    P("  erste 15 = beide Teams unter 15 Spielen (Spielerpunkte: Spieler mit 1-9 bisherigen Spielen), Rest = uebrige. Schwellen mit unter 100 Tipps sind als nicht aussagekraeftig gekennzeichnet (* in den Teilmengen-Tabellen).")
    P("")

    ALLM = [("Sieger (Favorit des Modells)", [("alle", "alle Spiele"), ("Favorit Heim", "Favorit Heim"), ("Favorit Gast", "Favorit Gast")]),
            ("Spread (Seite mit der hoeheren Deckungs-Chance, Linien mu-5 .. mu+5)", [("alle", "alle Tipps"), ("Favorit-Seite", "Favorit-Seite"), ("Aussenseiter-Seite", "Aussenseiter-Seite")]),
            ("Total (nur Over, Linien mu .. mu-5)", [("alle", "Over")]),
            ("Team Total (nur Over, Linien mu .. mu-5)", [("Heim", "Heim"), ("Gast", "Gast"), ("alle", "Heim und Gast zusammen")])]
    P("1-3 TIPPS, TREFFERQUOTE, BREAK-EVEN, VERLUSTSERIEN JE SCHWELLE")
    for mname, grps in ALLM:
        P(f"MARKT: {mname}  ({n} Spiele)")
        for key, lab in grps:
            if key in markets[mname]:
                main_table(lab, markets[mname][key])
    P(f"MARKT: Spielerpunkte (Over je Meilenstein k = 5..40; 2024-25 und 2025-26, {Gp} Spiele)")
    for gname in GN + ["alle Spieler"]:
        main_table(f"{gname} ({int((PL[gname].p >= 0.5).sum())} Tipps ab 50 %)", PL[gname])

    P("4 TEILMENGEN: ERSTE/ZWEITE HAELFTE UND ERSTE 15 TEAMSPIELE GEGEN REST (bei Spielerpunkten: 1-9 bisherige Spiele gegen ab 10)")
    for mname, grps in ALLM:
        P(f"MARKT: {mname}")
        for key, lab in grps:
            if key in markets[mname]:
                split_table(lab, markets[mname][key])
    P("MARKT: Spielerpunkte")
    for gname in GN + ["alle Spieler"]:
        split_table(gname, PL[gname])

    P("5 ZUSAMMENFASSUNG JE MARKT")
    P(f"  Frage 1: Ab welcher Schwelle liegt die Trefferquote in BEIDEN Haelften mindestens {100 * GOAL:.1f} % (Break-even Quote 1,50 + 3 PP)? 'Durchgehend' = auch fuer alle hoeheren Schwellen mit mindestens 100 Tipps je Haelfte.")
    STAR = {}
    USER = {"Sieger (Favorit des Modells)": ("alle", [(0.70, "alle Spiele")]),
            "Spread (Seite mit der hoeheren Deckungs-Chance, Linien mu-5 .. mu+5)": ("alle", [(0.60, "alle Tipps")]),
            "Total (nur Over, Linien mu .. mu-5)": ("alle", [(0.60, "Rest"), (0.65, "erste 15 Teamspiele")]),
            "Team Total (nur Over, Linien mu .. mu-5)": ("alle", [(0.60, "Rest"), (0.65, "erste 15 Teamspiele")])}
    for mname, grps in ALLM:
        P(f"MARKT: {mname}")
        for key, lab in grps:
            if key in markets[mname]:
                ut = USER[mname][1] if key == USER[mname][0] else None
                STAR[(mname, key)] = summary(lab, markets[mname][key], ut)[0]
    P("MARKT: Spielerpunkte")
    for gname in GN + ["alle Spieler"]:
        ut = [(0.80, "Starter mit >= 10 Spielen")] if gname == GN[0] else None
        STAR[("Spielerpunkte", gname)] = summary(gname, PL[gname], ut)[0]

    P("EMPFEHLUNG (aus den Zahlen oben; keine Aenderung am Produktivmodell)")
    P("  Kriterium: kleinste Schwelle, ab der die Trefferquote in beiden Haelften durchgehend mindestens das Ziel erreicht (>= 100 Tipps je Haelfte). Wo keine Schwelle das schafft, gilt: nicht empfohlen.")
    for (mname, key), star in STAR.items():
        P(f"  {mname.split(' (')[0]} / {key}: " + (f"Mindest-Chance {int(round(100 * star))} %" if star is not None else "keine Schwelle erreicht das Ziel in beiden Haelften"))
    P("")
    P("6 EHRLICHE ZAHLEN")
    P("  Tipps je Schwelle stehen in den Tabellen oben; Schwellen mit unter 100 Tipps sind gekennzeichnet. Linien eines Spiels sind korreliert (Intervalle nach Spielen). Die Spieler-Tipps stammen aus 2 Saisons, die Team-Maerkte aus 1 Saison (2025-26):")
    P("  Konstanten des Produktivmodells (Sigmas, Blowout-Kurve, league_ppm) sind teils in-sample. Ohne Quoten: Break-even-Quote ist nur die Hochrechnung 1 / Trefferquote; echte Quoten, Abzug des Buchmachers und Linien-Verfuegbarkeit sind nicht gemessen.")
    P("  Spreads/Totals: die Hauptlinie (k = 0) ist 50:50 per Konstruktion; hohe Schwellen sind bei Team-Maerkten gar nicht erreichbar (z. B. Total Over bei 5 Punkten Abstand hat nur etwa 60 % Modell-Chance).")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))

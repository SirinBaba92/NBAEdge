"""
Auswertung der Minutenprognose (Zwischenstaende von analysis/backtest_player_minutes.py). NUR LESEND, schreibt nur analysis/reports/player_minutes.txt.
Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_player_minutes_report.py
Fehler = Ist-Minuten minus Prognose-Minuten (Spielerzeilen mit > 0 Minuten, "wenn er spielt"); jede Spielerzeile einzeln; alle Intervalle (95 %) Bootstrap NACH SPIELEN (beide Teams eines Spiels zusammen, 600 Ziehungen).
Hauptauswertung gepoolt 2024-25 + 2025-26 (Seasons mit Vorsaison im Verlauf); 2023-24 (ohne Vorsaison) nur in der Gesamtzeile je Saison.
"""
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
TMP = Path("/private/tmp/claude-501/-Users-baranalturk-Desktop-NBAEdge/76ad3d4f-3f38-4b80-9c53-3d58597b513a/scratchpad/pm")
OUT = HERE / "reports" / "player_minutes.txt"
NB = 600
MIN_ROWS = 100
KS = np.arange(1, 61)
SEAS = ["2023-24", "2024-25", "2025-26"]


def load(season, variant):
    f = TMP / f"{season}_{variant}.npz"
    return {k: v for k, v in np.load(f).items()} if f.exists() else None


# --------------------------------------------------------------------------------------------- Zusammenfuehren
def stack(season_list, variant="base"):
    parts, off = [], 0
    for s in season_list:
        d = load(s, variant)
        if d is None:
            continue
        d = dict(d)
        d["gid"] = d["gi"] + off
        d["season"] = np.full(len(d["gi"]), s)
        off += int(d["n_games_total"][0])
        parts.append(d)
    keys = [k for k in parts[0] if k not in ("n_games_total",)]
    return {k: np.concatenate([p[k] for p in parts]) for k in keys}, off


def gstat(x, mask, gid, G):
    return np.bincount(gid[mask], weights=x[mask], minlength=G), np.bincount(gid[mask], minlength=G).astype(float)


_rng = np.random.default_rng(11)
_W = {}


def weights(G):
    if G not in _W:
        r = np.random.default_rng(100 + G)
        _W[G] = np.stack([np.bincount(r.integers(0, G, G), minlength=G) for _ in range(NB)]).astype(float)
    return _W[G]


def ci(num, den, G):
    if den.sum() == 0:
        return (np.nan,) * 3
    W = weights(G)
    bs = (W @ num) / np.maximum(W @ den, 1e-12)
    return float(num.sum() / den.sum()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def f2(t, d=2):
    return "n/a" if not np.isfinite(t[0]) else f"{t[0]:+.{d}f} [{t[1]:+.{d}f}; {t[2]:+.{d}f}]"


def f2u(t, d=2):
    return "n/a" if not np.isfinite(t[0]) else f"{t[0]:.{d}f} [{t[1]:.{d}f}; {t[2]:.{d}f}]"


L = []
P = L.append


def row_group_table(title, D, G, X, groups):
    P(f"  {title}")
    P(f"    {'Gruppe':44s} {'Zeilen':>7s} {'Bias [95 %]':>22s} {'mittlerer Betrag [95 %]':>26s}  Ø Prognose / Ø Ist")
    err = D["min"] - D[f"emin_{X}"]
    for nm, mk in groups:
        n = int(mk.sum())
        if n == 0:
            continue
        b = ci(*gstat(err, mk, D["gid"], G), G)
        a = ci(*gstat(np.abs(err), mk, D["gid"], G), G)
        flag = "   (< 100 Zeilen: nicht aussagekraeftig)" if n < MIN_ROWS else ""
        P(f"    {nm:44s} {n:7d} {f2(b):>22s} {f2u(a):>26s}  {D[f'emin_{X}'][mk].mean():5.1f} / {D['min'][mk].mean():5.1f}{flag}")


def slope_ci(x, y, mask, gid, G):
    """OLS-Steigung y auf x (nur mask) mit Bootstrap nach Spielen."""
    cols = [np.ones(len(x)), x, y, x * x, x * y]
    S = [np.bincount(gid[mask], weights=c[mask], minlength=G) for c in cols]
    W = weights(G)

    def sl(n, sx, sy, sxx, sxy):
        return (sxy - sx * sy / n) / np.maximum(sxx - sx * sx / n, 1e-12)
    pt = sl(*[s.sum() for s in S])
    bs = sl(*[W @ s for s in S])
    return float(pt), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


# --------------------------------------------------------------------------------------------- Hauptteil
def main():
    base_all, Gall = stack(SEAS)
    pool_list = ["2024-25", "2025-26"]
    D, G = stack(pool_list)
    P("MINUTENPROGNOSE DES SPIELER-MODELLS: IST-STAND UND VARIANTEN (walk-forward, nur echte Boxscores, ohne Quoten)")
    P("Skripte analysis/backtest_player_minutes.py (Replays) und analysis/backtest_player_minutes_report.py (Auswertung); beide lesen nur. Fehler = Ist-Minuten minus Prognose-Minuten (positiv: der Spieler spielt mehr als prognostiziert).")
    P("A = rohe Prognose (minutes.mean mit Blowout-Abschlag), B = Teamabgleich (Starter-Obergrenze 36, Bank auf 240 skaliert; Ausfaelle unbekannt). Gepoolt 2024-25 + 2025-26 (Vorsaison im Verlauf); 2023-24 hat keine Vorsaison im Cache.")
    P("")
    P("0 DATENLAGE")
    P(f"  Spielerdateien: 2023-24, 2024-25, 2025-26 (vollstaendig); 2026-27 nur {1181} Zeilen / wenige Tage und im Cache ohne Teamspiele fuer den Replay -> nicht ausgewertet.")
    for s in SEAS:
        d = load(s, "base")
        P(f"  {s}: {len(d['gi']):6d} Spielerzeilen, {len(np.unique(d['gi'])):4d} Spiele, {len(np.unique(d['date'])):3d} Spieltage, {len(np.unique(d['pid'])):3d} Spieler" + ("  (OHNE Vorsaison im Verlauf)" if s == "2023-24" else ""))
    P(f"  Gepoolt 2024-25 + 2025-26: {len(D['gi'])} Spielerzeilen, {G} Spiele, {sum(len(np.unique(load(s, 'base')['date'])) for s in pool_list)} Spieltage.")
    P("  Spieler ohne Verlauf (Rookies ohne eine Zeile vor dem Spiel) bekommen keine Prognose und fehlen hier (frueher gemessen: ca. 1,4 % der Einsaetze) -> 'neue Spieler' sind unterrepraesentiert.")
    P("  Konstanten (Blowout-Kurve, Sigma) stammen aus 2025-26: fuer 2025-26 teils in-sample.")
    P("")

    # ------------------------------------------------------------------ 1
    P("1 MINUTENFEHLER")
    P("1.0 Gesamt je Saison")
    P(f"  {'Saison':10s} {'Variante':9s} {'Zeilen':>7s} {'Bias [95 %]':>22s} {'mittlerer Betrag [95 %]':>26s}")
    for s in SEAS + ["gepoolt"]:
        d, g = (D, G) if s == "gepoolt" else stack([s])
        for X in ("A", "B"):
            e = d["min"] - d[f"emin_{X}"]
            msk = np.ones(len(e), bool)
            P(f"  {s:10s} {X:9s} {len(e):7d} {f2(ci(*gstat(e, msk, d['gid'], g), g)):>22s} {f2u(ci(*gstat(np.abs(e), msk, d['gid'], g), g)):>26s}" + ("   (ohne Vorsaison)" if s == "2023-24" else ""))
    P("")
    rc, new = D["rank_cum"], D["new"]
    for X in ("A", "B"):
        em = D[f"emin_{X}"]
        P(f"1.1 Aufteilungen, Variante {X} ({'roh' if X == 'A' else 'Teamabgleich'}), gepoolt 2024-25 + 2025-26")
        row_group_table("(a) Rolle (Top 5 / Platz 6-9 nach Minuten des Teams bis dahin; 'neu' = keine Vorjahresminuten im selben Team, ueberschneidungsfrei zuerst vergeben)", D, G, X, [
            ("Starter (Top 5), nicht neu", (rc <= 5) & (new == 0)), ("Rotation (Platz 6-9), nicht neu", (rc >= 6) & (rc <= 9) & (new == 0)), ("uebrige (Platz 10+), nicht neu", (rc >= 10) & (new == 0)),
            ("neue Spieler (Rookies/Wechsler, jeder Rang)", new == 1), ("   davon Starter-Rang (Top 5)", (new == 1) & (rc <= 5)), ("   davon Rotation (6-9)", (new == 1) & (rc >= 6) & (rc <= 9)), ("   davon uebrige", (new == 1) & (rc >= 10))])
        row_group_table("(b) Minutenklasse der Prognose", D, G, X, [("Prognose unter 15 Min.", em < 15), ("Prognose 15 bis 25", (em >= 15) & (em < 25)), ("Prognose 25 bis 32", (em >= 25) & (em < 32)), ("Prognose ab 32", em >= 32)])
        row_group_table("(c) Saisonphase (eigenes Team)", D, G, X, [("erste 15 Teamspiele", D["gp"] < 15), ("Rest der Saison", D["gp"] >= 15)])
        row_group_table("(d) Verlaengerung", D, G, X, [("Spiel mit Verlaengerung", D["ot"] == 1), ("Spiel ohne Verlaengerung", D["ot"] == 0)])
        row_group_table("(e) Spielverlauf (Endstand-Differenz) und Zusammenhang mit dem Modell-Spread", D, G, X, [
            ("Endstand-Differenz ab 20 Punkten", D["absm"] >= 20), ("Endstand-Differenz unter 20", D["absm"] < 20), ("   Starter, Differenz ab 20", (rc <= 5) & (D["absm"] >= 20)), ("   Starter, Differenz unter 20", (rc <= 5) & (D["absm"] < 20)),
            ("Starter, Team ist Favorit (Spread > 0)", (rc <= 5) & (D["tspread"] > 0)), ("Starter, Team ist Aussenseiter (Spread < 0)", (rc <= 5) & (D["tspread"] < 0))])
        err = D["min"] - em
        ab = np.abs(D["tspread"])
        P("    Steigung des Minutenfehlers gegen den Betrag des Modell-Spreads (Minuten je Spread-Punkt; negativ = bei grossem erwarteten Vorsprung/Rueckstand weniger Minuten als prognostiziert):")
        for nm, mk in (("Starter (Top 5), Favorit", (rc <= 5) & (D["tspread"] > 0)), ("Starter (Top 5), Aussenseiter", (rc <= 5) & (D["tspread"] < 0)), ("Starter, alle", rc <= 5),
                       ("Rotation (6-9), alle", (rc >= 6) & (rc <= 9)), ("alle Zeilen", np.ones(len(err), bool))):
            P(f"      {nm:34s} Zeilen {int(mk.sum()):6d}  {f2(slope_ci(ab, err, mk, D['gid'], G), 3)}")
        P("")

    # ------------------------------------------------------------------ 2 Zerlegung
    P("2 ZERLEGUNG DES PUNKTEFEHLERS (Ist-Punkte minus Prognose-Punkte = Minutenteil + Punkte-pro-Minute-Teil)")
    P("  Minutenteil = Ist-Punkte pro Minute x (Ist-Minuten - Prognose-Minuten); ppm-Teil = Rest = Prognose-Minuten x (Ist-ppm - Prognose-ppm), Prognose-ppm = Prognose-Punkte / Prognose-Minuten. Beide Teile summieren sich exakt zum Punktefehler.")
    P("  Anteil am quadratischen Fehler: Summe(Fehler x Teil) / Summe(Fehler^2); beide Anteile zusammen = 100 %. Mittlere Teile in Punkten zeigen die Richtung (Bias).")
    P(f"  {'Gruppe':26s} {'Var.':5s} {'Zeilen':>7s} {'Punktefehler Ø':>20s} {'Minutenteil Ø':>20s} {'ppm-Teil Ø':>20s} {'Anteil Minuten (quadr.)':>26s} {'Anteil ppm (quadr.)':>26s}")
    for nm, d, g in [("2024-25", *stack(["2024-25"])), ("2025-26", *stack(["2025-26"])), ("gepoolt", D, G), ("2023-24 (ohne Vorsaison)", *stack(["2023-24"]))]:
        for X in ("A", "B"):
            ppm_act = d["pts"] / d["min"]
            pm_ = ppm_act * (d["min"] - d[f"emin_{X}"])
            tot = d["pts"] - d[f"epts_{X}"]
            pp_ = tot - pm_
            msk = np.ones(len(tot), bool)
            cn = gstat(np.ones(len(tot)), msk, d["gid"], g)[0]
            tb = ci(gstat(tot, msk, d["gid"], g)[0], cn, g); mb = ci(gstat(pm_, msk, d["gid"], g)[0], cn, g); pb = ci(gstat(pp_, msk, d["gid"], g)[0], cn, g)
            den = gstat(tot * tot, msk, d["gid"], g)[0]
            sm = ci(gstat(tot * pm_, msk, d["gid"], g)[0], den, g); sp = ci(gstat(tot * pp_, msk, d["gid"], g)[0], den, g)
            P(f"  {nm:26s} {X:5s} {len(tot):7d} {f2(tb):>20s} {f2(mb):>20s} {f2(pb):>20s} {100*sm[0]:6.1f} % [{100*sm[1]:.1f}; {100*sm[2]:.1f}] {100*sp[0]:6.1f} % [{100*sp[1]:.1f}; {100*sp[2]:.1f}]")
    P("  Bemerkung: Die Anteile sind additive Beitraege zum mittleren quadratischen Fehler; ein Teil kann ueber 100 % liegen, wenn der andere negativ beitraegt (Gegenlauf).")
    P("")

    # ------------------------------------------------------------------ 3 + 4 Varianten
    def variant_arrays(season, v):
        return load(season, v)

    def brier_rows(d, key, mask_ref):
        p = d[key].astype(np.float64)
        y = (d["pts"][:, None] >= KS[None, :]).astype(np.float64)
        se = ((p - y) ** 2 * mask_ref).sum(axis=1)
        return se, mask_ref.sum(axis=1).astype(float)

    def compare(season, v, X, ref_rank_key, label_halves=True):
        """Variante v gegen base in einer Saison (Zeilen gleich geordnet). Rueckgabe dict je Hoelfte {n_rows, dBrier, dMAE_starter, dMAE_all, base/var-Kennzahlen}."""
        b, a = load(season, "base"), load(season, v)
        assert len(b["gi"]) == len(a["gi"]) and np.array_equal(b["gi"], a["gi"]) and np.array_equal(b["pid"], a["pid"]), f"Zeilen verschieden {season} {v}"
        gid = b["gi"]; Gs = int(b["n_games_total"][0])
        pb = b[f"p{X}"].astype(np.float64)
        mref = ((pb >= 0.05) & (pb <= 0.95)).astype(np.float64)
        seb, cnt = brier_rows(b, f"p{X}", mref)
        sev, _ = brier_rows(a, f"p{X}", mref)
        eb, ev = b["min"] - b[f"emin_{X}"], a["min"] - a[f"emin_{X}"]
        starter = (b[ref_rank_key] <= 5)
        res = {}
        for hn, hm in (("ganze Saison", np.ones(len(gid), bool)), ("Haelfte 1", b["half"] == 0), ("Haelfte 2", b["half"] == 1)):
            r = {}
            r["n"] = int(hm.sum()); r["n_starter"] = int((hm & starter).sum())
            num_b, den_b = gstat(seb, hm, gid, Gs)[0], gstat(cnt, hm, gid, Gs)[0]
            r["brier_base"] = ci(num_b, den_b, Gs); r["brier_var"] = ci(gstat(sev, hm, gid, Gs)[0], den_b, Gs)
            r["dbrier"] = ci(gstat(sev - seb, hm, gid, Gs)[0], den_b, Gs)
            sm = hm & starter
            n_s = gstat(np.ones(len(gid)), sm, gid, Gs)[0]
            r["mae_s_base"] = ci(gstat(np.abs(eb), sm, gid, Gs)[0], n_s, Gs); r["mae_s_var"] = ci(gstat(np.abs(ev), sm, gid, Gs)[0], n_s, Gs)
            r["dmae_s"] = ci(gstat(np.abs(ev) - np.abs(eb), sm, gid, Gs)[0], n_s, Gs)
            r["bias_s_var"] = ci(gstat(ev, sm, gid, Gs)[0], n_s, Gs)
            n_a = gstat(np.ones(len(gid)), hm, gid, Gs)[0]
            r["mae_a_base"] = ci(gstat(np.abs(eb), hm, gid, Gs)[0], n_a, Gs); r["mae_a_var"] = ci(gstat(np.abs(ev), hm, gid, Gs)[0], n_a, Gs)
            r["dmae_a"] = ci(gstat(np.abs(ev) - np.abs(eb), hm, gid, Gs)[0], n_a, Gs)
            res[hn] = r
        return res

    NAMES = {"cap38": "Starter-Obergrenze 38", "cap40": "Starter-Obergrenze 40", "capnone": "keine Starter-Obergrenze", "sason": "Saisonschnitt (gleich gewichtet)", "l5": "letzte 5 Spiele", "l10": "letzte 10 Spiele", "mix": "Mischung 50 % Saisonschnitt + 50 % letzte 5"}

    def variant_block(title, variants, X, ref_rank_key):
        P(title)
        P("  Brier = Meilenstein-Chancen P(Punkte >= k), nur (Spieler, k) mit 5 % <= p <= 95 % der heutigen Variante; Minutenfehler der Starter = Betrag bei Top-5-Spielern. d = Variante minus heute (negativ = besser), Intervall 95 %, Bootstrap nach Spielen, Einheit Brier x10^-3, Minuten.")
        verdicts = {}
        for season in ("2025-26", "2024-25"):
            P(f"  Pruefsaison {season}{' (Hauptpruefung)' if season == '2025-26' else ' (zweite Pruefung)'}")
            P(f"    {'Variante':46s} {'Zeitraum':13s} {'Zeilen':>7s} {'Brier heute':>9s} {'dBrier x10^-3 [95 %]':>26s} {'Starter-MAE heute':>10s} {'dStarter-MAE [95 %]':>24s} {'dMAE alle [95 %]':>22s}")
            for v in variants:
                res = compare(season, v, X, ref_rank_key)
                for hn in ("Haelfte 1", "Haelfte 2", "ganze Saison"):
                    r = res[hn]
                    P(f"    {NAMES[v]:46s} {hn:13s} {r['n']:7d} {r['brier_base'][0]:9.4f} {f2((r['dbrier'][0]*1000, r['dbrier'][1]*1000, r['dbrier'][2]*1000)):>26s} {r['mae_s_base'][0]:10.3f} {f2(r['dmae_s'], 3):>24s} {f2(r['dmae_a'], 3):>22s}")
                better = all(res[h]["dbrier"][0] < 0 and res[h]["dmae_s"][0] < 0 for h in ("Haelfte 1", "Haelfte 2"))
                verdicts[(season, v)] = better
                P(f"      => {NAMES[v]} auf BEIDEN Haelften besser (Brier UND Starter-Minutenfehler): {'JA' if better else 'nein'}")
        return verdicts

    P("3 STARTER-OBERGRENZE IM TEAMABGLEICH (Variante B; heute 36 Minuten)")
    P("  Starter = die 5 Spieler mit den meisten erwarteten Minuten im Teamabgleich (rank_B <= 5); nur dort wirkt die Grenze.")
    ver3 = variant_block("", ["cap38", "cap40", "capnone"], "B", "rank_B")
    P("")
    P("4 AKTUALITAET DER MINUTEN (Gewichtung der vergangenen Spiele)")
    P("  Starter = Top 5 nach Minuten des Teams bis dahin (Variante unabhaengig). Heute: exponentiell fallend, Halbwertszeit 8 Spiele, Schrumpfung zur Vorsaison n / (n + 8).")
    ver4 = {}
    for X in ("A", "B"):
        P(f"4{'a' if X == 'A' else 'b'} Variante {X} ({'roh' if X == 'A' else 'Teamabgleich'})")
        ver4[X] = variant_block("", ["sason", "l5", "l10", "mix"], X, "rank_cum")
    P("")

    # ------------------------------------------------------------------ 5 OT
    P("5 ERWARTETE VERLAENGERUNG (nur ausgerechnet, nicht eingebaut)")
    games_ot = []
    for s in pool_list:
        d = load(s, "base")
        gi_, ot_ = d["gi"], d["ot"]
        u, idx = np.unique(gi_, return_index=True)
        games_ot.append(ot_[idx].mean())
    p_ot = float(np.mean(games_ot))
    P(f"  Anteil Spiele mit Verlaengerung (Spiele mit Spielerzeilen): 2024-25 {100*games_ot[0]:.1f} %, 2025-26 {100*games_ot[1]:.1f} %.")
    P("  Beitrag = Anteil der Verlaengerungsspiele x (mittlerer Minutenfehler in Verlaengerungsspielen - ohne Verlaengerung); Ist-Bias ist der mittlere Fehler ueber alle Spiele.")
    P(f"  {'Gruppe':28s} {'Var.':4s} {'Bias gesamt':>12s} {'Bias ohne OT':>13s} {'Bias in OT-Spielen':>19s} {'Extra-Minuten in OT':>20s} {'Beitrag (Haeufigkeit x Extra)':>30s} {'Bias nach Abzug':>16s}")
    for X in ("A", "B"):
        err = D["min"] - D[f"emin_{X}"]
        for nm, mk in (("alle Spieler", np.ones(len(err), bool)), ("Starter (Top 5)", rc <= 5), ("Rotation (6-9)", (rc >= 6) & (rc <= 9)), ("uebrige (10+)", rc >= 10)):
            o, n_ = mk & (D["ot"] == 1), mk & (D["ot"] == 0)
            e_all, e_no, e_ot = err[mk].mean(), err[n_].mean(), err[o].mean()
            share = o.sum() / mk.sum()
            extra = e_ot - e_no
            P(f"  {nm:28s} {X:4s} {e_all:+12.2f} {e_no:+13.2f} {e_ot:+19.2f} {extra:+20.2f} {share*extra:+14.2f} (Zeilenanteil {100*share:.1f} %) {e_all - share*extra:+16.2f}")
    P("  Lesart: 'Beitrag' ist der Teil des mittleren Minutenfehlers, der allein aus Verlaengerungen stammt; ein fester Aufschlag in dieser Hoehe wuerde nur den Bias verschieben. Der Fehler je Spiel (Betrag) bleibt, weil eine Verlaengerung vorab nicht bekannt ist.")
    P("")

    # ------------------------------------------------------------------ Zusammenfassung
    P("ZUSAMMENFASSUNG")
    for tag, ver in (("Starter-Obergrenze (B)", ver3), ("Gewichtung roh (A)", {k: v for k, v in ver4["A"].items()}), ("Gewichtung Teamabgleich (B)", {k: v for k, v in ver4["B"].items()})):
        ok = [f"{NAMES[v]}" for (s, v), b in ver.items() if s == "2025-26" and b]
        ok2 = [f"{NAMES[v]}" for (s, v), b in ver.items() if s == "2024-25" and b]
        P(f"  {tag}: besser auf beiden Haelften 2025-26: {', '.join(ok) if ok else 'keine Variante'}; 2024-25: {', '.join(ok2) if ok2 else 'keine Variante'}.")
    P("  Regel: Aenderung nur bei besserem Brier UND besserem Minutenfehler auf beiden Pruefhaelften; Stufen mit unter 100 Zeilen sind nicht aussagekraeftig.")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

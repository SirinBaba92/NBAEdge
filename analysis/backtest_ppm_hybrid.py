"""
Experiment 5.1, Stufe 2: Hybrid fuer Spieler mit wenigen Spielen, geprueft an den Chancen der Spielerpunkte-Meilensteine (P(Punkte >= k), k = 1..60). NUR ANALYSE, kein Netz;
engine/player_forecast.py und alle bestehenden Dateien bleiben unveraendert (alles im Speicher dieses Skripts). Schreibt analysis/results/ppm_hybrid.txt.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_ppm_hybrid.py [--tmp ORDNER]
(Der Replay 2023-24 wird bei Bedarf wie in analysis/backtest_minutes_empirical.py neu gerechnet und im Temp-Ordner abgelegt, ca. 1 Minute.)

ENTSCHEIDUNGSREGEL (vorab festgelegt): Eine Variante zaehlt als besser, wenn sie in allen drei Testsaisons in der Gruppe 1 bis 9 bisherige Spiele sowohl Brier als auch Log-Loss gegenueber R senkt
UND die Luecke zwischen mittlerer Chance und Trefferquote ab 80 % Chance (Betrag) kleiner wird als bei R. Parameter nur aus zwei Saisons gewaehlt, auf der dritten getestet.

Rechnung (Chancenrechnung wie engine/player_forecast.forecast_player: Punktewert x je (Spiel im Verlauf, Minutenpunkt) = ppm_i * m_j, Gewichte w, Normalglaettung h = 1 + 0,05 x; Bausteine aus dem Replay von
analysis/backtest_player_calibration.py, wie in analysis/backtest_minutes_empirical.py)
- R:  unveraendert. Alle Spieler mit mindestens 10 bisherigen Spielen (alle Saisons zusammen, aus data/cache gezaehlt) bleiben in JEDER Variante exakt R (gleicher Rechenweg).
- H0: Gruppe 1 bis 9 bisherige Spiele: alle Punktewerte x werden mit S / E_R multipliziert (E_R = Mittelwert der Punkte in R, S = Mittelwert aus der Zerlegung von analysis/ppm_decomposition.py, Gesamtverlauf, k und k_min aus
  zwei Saisons gewaehlt). Der Mittelwert ist danach genau S; die Streuung der Punktewerte bleibt im Verhaeltnis zum Mittelwert wie in R (Variationskoeffizient gleich).
- H1_w: wie H0, danach werden die Punktewerte um ihren Mittelwert S gespreizt: x -> max(0, S + w (x - S)), w aus {1,2, 1,4, 1,6}. Die Streuung wird also VOR der Normalglaettung in der Punktewert-Mischung (Spielverlauf x Minutenpunkte)
  vergroessert, der Glaettungskern h = 1 + 0,05 x bleibt. Die Begrenzung bei 0 hebt den Mittelwert minimal (im Bericht: mittlere erwartete Punkte je Variante).
- Kontrolle C_w: nur die Streuung (gleiche Spreizung um E_R), Mittelwert wie R.
- w wird je Anpassung aus den zwei Trainingssaisons mit kleinstem Brier in der Gruppe 1 bis 9 gewaehlt (gleich fuer H1 und Kontrolle, getrennt gewaehlt).
Ausschluesse: Spiel 0022400061, Verlaengerungsspiele (Teamsumme der Spielerminuten > 245; Training und Auswertung).
"""
import argparse
import sys
import tempfile
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.special import ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from analysis import backtest_minutes_empirical as be  # noqa: E402
from analysis import ppm_decomposition as pdc  # noqa: E402

HOME = Path.home()
SEASONS = ("2023-24", "2024-25", "2025-26")
KS_ALL = np.arange(1, 61)
WS = (1.2, 1.4, 1.6)
LEVELS = (0.50, 0.65, 0.80, 0.90)
FEW = 10                                                   # unter 10 bisherigen Spielen: Gruppe 1 bis 9
GROUPS = ("1-9 Spiele", "ab 10 Spielen")
EPS = 1e-6
OUT = HERE / "results" / "ppm_hybrid.txt"


# ----------------------------------------------------------------------------- Kern (rein, getestet)
def mixture(ppm: np.ndarray, w_p: np.ndarray, m_k: np.ndarray) -> tuple:
    x = (ppm[:, None] * m_k[None, :]).ravel()
    w = (w_p[:, None] * np.full(len(m_k), 1.0 / len(m_k))[None, :]).ravel()
    return x, w


def smooth_probs(x: np.ndarray, w: np.ndarray, ns: np.ndarray) -> np.ndarray:
    h = 1.0 + 0.05 * x
    p = (w[None, :] * (1.0 - ndtr((ns[:, None] - 0.5 - x[None, :]) / h[None, :]))).sum(axis=1)
    return np.minimum.accumulate(np.clip(p, 0.0, 1.0))


def transform(x: np.ndarray, w: np.ndarray, mode: str, s: float, spread: float) -> np.ndarray:
    """Punktewerte der Variante. mode: 'R' unveraendert; 'H' Mittelwert auf s (multiplikativ), danach Spreizung um s mit Faktor spread; 'C' Mittelwert wie R, nur Spreizung um E_R."""
    if mode == "R":
        return x
    er = float((w * x).sum())
    if mode == "C":
        return np.maximum(0.0, er + spread * (x - er)) if spread != 1.0 else x
    if not np.isfinite(s) or er <= 0 or s <= 0:
        return x                                           # kein brauchbarer Wert aus der Zerlegung: wie R
    x1 = x * (s / er)
    return np.maximum(0.0, s + spread * (x1 - s)) if spread != 1.0 else x1


def variant_probs(ppm, w_p, m_k, ngames: int, mode: str, s: float, spread: float, ns=KS_ALL) -> tuple:
    """(Chancen fuer ns, mittlere erwartete Punkte). Spieler mit >= 10 bisherigen Spielen: immer R (gleicher Rechenweg)."""
    x, w = mixture(ppm, w_p, m_k)
    if ngames >= FEW:
        mode = "R"
    x2 = transform(x, w, mode, s, spread)
    return smooth_probs(x2, w, ns), float((w * x2).sum())


def metrics(p: np.ndarray, hit: np.ndarray) -> dict:
    if len(p) == 0:
        return {"n": 0, "brier": float("nan"), "ll": float("nan"), "bias": float("nan")}
    pc = np.clip(p, EPS, 1 - EPS)
    return {"n": len(p), "brier": float(np.mean((p - hit) ** 2)), "ll": float(-np.mean(hit * np.log(pc) + (1 - hit) * np.log(1 - pc))), "bias": float(p.mean() - hit.mean())}


def calibration(p: np.ndarray, hit: np.ndarray, level: float) -> tuple:
    m = p >= level
    n = int(m.sum())
    return (n, float(p[m].mean()), float(hit[m].mean())) if n else (0, float("nan"), float("nan"))


def gap80(p: np.ndarray, hit: np.ndarray) -> float:
    n, mp, hr = calibration(p, hit, 0.80)
    return abs(mp - hr) if n else float("nan")


def decide(per: dict, ref: str = "R") -> dict:
    """per[Variante][Saison] = {'brier','ll','gap80'} fuer Gruppe 1-9. Regel: in allen Saisons Brier und LL kleiner als R und Luecke ab 80 % kleiner."""
    out = {}
    for v, s_ in per.items():
        if v == ref:
            continue
        b = all(s_[s]["brier"] < per[ref][s]["brier"] for s in s_)
        l = all(s_[s]["ll"] < per[ref][s]["ll"] for s in s_)
        g = all(s_[s]["gap80"] < per[ref][s]["gap80"] for s in s_)
        out[v] = {"Brier": b, "LL": l, "Luecke80": g, "Regel": b and l and g}
    return out


# ----------------------------------------------------------------------------- Rechnung mit Prozessen
def _worker(job):
    items, mode, spread = job
    probs = np.zeros((len(items), len(KS_ALL))); ep = np.zeros(len(items))
    for j, (ppm, w_p, m_k, ng, s) in enumerate(items):
        probs[j], ep[j] = variant_probs(ppm, w_p, m_k, ng, mode, s, spread)
    return probs, ep


def compute(items: list, mode: str, spread: float, pool: Pool) -> tuple:
    chunks = [items[i::16] for i in range(16)]
    parts = pool.map(_worker, [(c, mode, spread) for c in chunks])
    n = len(items)
    probs, ep = np.zeros((n, len(KS_ALL))), np.zeros(n)
    for i, (pp, ee) in enumerate(parts):
        probs[i::16], ep[i::16] = pp, ee
    return probs, ep


# ----------------------------------------------------------------------------- Daten
def load_all(pbp: Path, cache: Path, tmp: Path) -> dict:
    """Zeilen aller drei Saisons (ohne Ausschluesse) mit Bausteinen, Verlauf, S-Vorhersage je gewaehltem (k, kmin) nachgereicht."""
    local = pdc.load_local(cache)
    hist = pdc.History(local)
    csv_rows = {s: pdc.load_forecast_rows(pbp, s) for s in SEASONS}
    link = {(r["season"], r["day"], r["pid"]): r for rs in csv_rows.values() for r in rs}
    if not be.rows_path("2023-24", pbp, tmp).exists():
        be.replay_2023(tmp)
    out = {"season": [], "items": [], "act": [], "ng": [], "agg": [], "lg": [], "emin": [], "ot": []}
    miss = 0
    for s in SEASONS:
        z = np.load(be.rows_path(s, pbp, tmp))
        d = {k: z[k] for k in z.files}
        for i in range(len(d["pid"])):
            day, pid = int(d["date"][i]), int(d["pid"][i])
            c = link.get((s, day, pid))
            if c is None:
                miss += 1
                continue
            a = hist.player(pid, day, "alle"); lg = hist.league(day)
            if a[5] < 1 or lg[0] <= 0:
                continue
            ppm = d["ppm_cat"][d["off"][i]:d["off"][i + 1]]; wp = d["wp_cat"][d["off"][i]:d["off"][i + 1]]
            out["season"].append(s); out["items"].append((ppm, wp, d["mk"][i])); out["act"].append(float(d["pts"][i])); out["ng"].append(int(a[5]))
            out["agg"].append(a); out["lg"].append(lg); out["emin"].append(float(d["emin"][i])); out["ot"].append(bool(c["ot"]))
    res = {k: (np.array(v) if k != "items" else v) for k, v in out.items()}
    res["unmatched"] = miss
    res["csv_rows"] = csv_rows
    res["hist"] = hist
    return res


def s_values(D: dict, k: float, kmin: float) -> np.ndarray:
    return pdc.predict(D["agg"], D["lg"], D["emin"], k, kmin)


# ----------------------------------------------------------------------------- Auswertung
def fmt_cal(c) -> str:
    return "-" if c[0] == 0 else f"{c[0]}/{100 * c[1]:.1f}%/{100 * c[2]:.1f}%"


def run(pbp: Path, cache: Path, tmp: Path, write=print) -> str:
    t0 = time.time()
    D = load_all(pbp, cache, tmp)
    T = pdc.build_table([r for s in SEASONS for r in D["csv_rows"][s]], D["hist"])           # Zeilen wie in Stufe 1 (Parameterwahl)
    T["ngames"] = T["agg"]["alle"][:, 5]
    season, ng, ot, act = D["season"], D["ng"], D["ot"], D["act"]
    base = ~ot
    few_idx = np.where(base & (ng < FEW))[0]
    many_idx = np.where(base & (ng >= FEW))[0]
    write(f"Zeilen: {len(season)} (davon Gruppe 1-9 ohne Verlaengerung: {len(few_idx)}, ab 10: {len(many_idx)}), ohne Zuordnung: {D['unmatched']}")
    hit = (act[:, None] >= KS_ALL[None, :]).astype(float)

    with Pool(8) as pool:
        # R fuer alle Zeilen (ohne Verlaengerung), Gruppe 1-9 und ab 10
        idx_all = np.concatenate([few_idx, many_idx])
        itemsR = [(*D["items"][i], int(ng[i]), np.nan) for i in idx_all]
        pR, eR = compute(itemsR, "R", 1.0, pool)
        PR = {int(i): j for j, i in enumerate(idx_all)}
        write(f"R fertig ({time.time() - t0:.0f} s)")
        folds, cache_v = {}, {}
        for test in SEASONS:
            train = [s for s in SEASONS if s != test]
            k, kmin, note = pdc.choose_params(T, train, "alle")
            folds[test] = (k, kmin, note)
            if (k, kmin) not in cache_v:
                S = s_values(D, k, kmin)
                items = [(*D["items"][i], int(ng[i]), float(S[i])) for i in few_idx]
                v = {"H0": compute(items, "H", 1.0, pool)}
                for w in WS:
                    v[f"H1_{w}"] = compute(items, "H", w, pool)
                    v[f"C_{w}"] = compute(items, "C", w, pool)
                cache_v[(k, kmin)] = v
                write(f"Varianten (k={k}, kmin={kmin}) fertig ({time.time() - t0:.0f} s)")

    posf = {int(i): j for j, i in enumerate(few_idx)}
    def rows_of(group, seasons_):
        idx = few_idx if group == "1-9 Spiele" else many_idx
        return np.array([i for i in idx if season[i] in seasons_], int)

    def p_of(variant, group, seasons_, k_kmin):
        idx = rows_of(group, seasons_)
        if variant == "R" or group != "1-9 Spiele":
            return idx, np.array([pR[PR[int(i)]] for i in idx]) if len(idx) else np.zeros((0, 60))
        pv = cache_v[k_kmin][variant][0]
        return idx, np.array([pv[posf[int(i)]] for i in idx]) if len(idx) else np.zeros((0, 60))

    out = [__doc__.split("Aufruf")[0].strip().split("\n")[0], "",
           "Hybrid fuer Spieler mit wenigen Spielen (Stufe 2) - Chancen der Meilensteine k = 1..60, Zeile = Spieler x Meilenstein; Treffer = Punkte >= k (beschreibend, Entscheidungsregel unten)",
           "Gruppen nach Zahl bisheriger Spiele (alle Saisons zusammen, ab 2023-24): 1-9 und ab 10. In der Gruppe ab 10 sind ALLE Varianten exakt R (gleicher Rechenweg).",
           "Varianten: R roh. H0 = Mittelwert der Punkte aus der Zerlegung S, Punktewerte multiplikativ umskaliert (Streuung im Verhaeltnis wie R). H1_w = H0 + Punktewerte um den Mittelwert mit Faktor w gespreizt (vor der Normalglaettung,",
           "Begrenzung bei 0). C_w = Kontrolle: nur Spreizung, Mittelwert wie R. Parameter je Anpassung nur aus den zwei Trainingssaisons gewaehlt; Test auf der dritten.",
           "Brier/Log-Loss kleiner = besser. Verzerrung = mittlere Chance minus Trefferquote (Prozentpunkte). Kalibrierung ab 50/65/80/90 %: Zeilen / mittlere Chance / Trefferquote.",
           "VORAB FESTGELEGTE REGEL: besser, wenn in allen drei Testsaisons in Gruppe 1-9 Brier UND Log-Loss kleiner als R sind und die Luecke (Betrag, Chance minus Trefferquote) ab 80 % kleiner wird.", "",
           "1. GEWAEHLTE PARAMETER"]
    chosen = {}
    for test in SEASONS:
        k, kmin, note = folds[test]
        train = [s for s in SEASONS if s != test]
        sc = {}
        for fam in ("H1", "C"):
            best = min(WS, key=lambda w: metrics(p_of(f"{fam}_{w}", "1-9 Spiele", train, (k, kmin))[1].ravel(), hit[p_of("R", "1-9 Spiele", train, (k, kmin))[0]][:, :].ravel())["brier"])
            sc[fam] = best
        chosen[test] = sc
        out.append(f"  Test {test}: S mit k = {k}, k_min = {kmin}" + (f" [{note}]" if note else "") + f"; w (H1) = {sc['H1']}, w (Kontrolle) = {sc['C']}")
    out.append("")

    names = ["R", "H0", "H1", "C"]
    store = {}
    for group in GROUPS:
        for v in names:
            for test in SEASONS + ("gesamt",):
                ps, hs, eps_, acts = [], [], [], []
                for t in (SEASONS if test == "gesamt" else (test,)):
                    k, kmin, _ = folds[t]
                    name = v if v in ("R", "H0") else f"{v}_{chosen[t][v]}"
                    idx, P = p_of(name, group, [t], (k, kmin))
                    if len(idx):
                        ps.append(P.ravel()); hs.append(hit[idx].ravel())
                        if group == "1-9 Spiele":
                            ep = np.array([cache_v[(k, kmin)][name][1][posf[int(i)]] for i in idx]) if v != "R" else np.array([eR[PR[int(i)]] for i in idx])
                        else:
                            ep = np.array([eR[PR[int(i)]] for i in idx])
                        eps_.append(ep); acts.append(act[idx])
                p, h = (np.concatenate(ps), np.concatenate(hs)) if ps else (np.zeros(0), np.zeros(0))
                store[(group, v, test)] = {"m": metrics(p, h), "cal": [calibration(p, h, l) for l in LEVELS], "gap80": gap80(p, h) if len(p) else float("nan"),
                                           "ep": float(np.concatenate(eps_).mean()) if eps_ else float("nan"), "act": float(np.concatenate(acts).mean()) if acts else float("nan"), "rows": sum(len(a) for a in acts)}
    cols = list(SEASONS) + ["gesamt"]
    out.append("2. TABELLEN")
    for group in GROUPS:
        out += [f"Gruppe {group}", "  " + "Kennzahl".ljust(24) + "".join(c.rjust(14) for c in cols)]
        out.append("  " + "Spielerzeilen".ljust(24) + "".join(str(store[(group, 'R', c)]["rows"]).rjust(14) for c in cols))
        out.append("  " + "Meilenstein-Zeilen".ljust(24) + "".join(str(store[(group, 'R', c)]["m"]["n"]).rjust(14) for c in cols))
        out.append("  " + "Punkte tatsaechlich (Ø)".ljust(24) + "".join(f"{store[(group, 'R', c)]['act']:.3f}".rjust(14) for c in cols))
        for v in names:
            out.append("  " + f"Punkte erwartet {v}".ljust(24) + "".join(f"{store[(group, v, c)]['ep']:.3f}".rjust(14) for c in cols))
        for key, lab, scale, dec in (("brier", "Brier", 1, 5), ("ll", "Log-Loss", 1, 5), ("bias", "Verzerrung (PP)", 100, 2)):
            for v in names:
                out.append("  " + f"{lab} {v}".ljust(24) + "".join(f"{scale * store[(group, v, c)]['m'][key]:.{dec}f}".rjust(14) for c in cols))
        for li, lvl in enumerate(LEVELS):
            for v in names:
                out.append("  " + f"ab {int(lvl * 100)} % {v}".ljust(24) + "".join(fmt_cal(store[(group, v, c)]["cal"][li]).rjust(24) for c in cols))
        out.append("")
    out.append("3. ENTSCHEIDUNGSREGEL (Gruppe 1-9 Spiele, drei Testsaisons)")
    per = {v: {t: {"brier": store[("1-9 Spiele", v, t)]["m"]["brier"], "ll": store[("1-9 Spiele", v, t)]["m"]["ll"], "gap80": store[("1-9 Spiele", v, t)]["gap80"]} for t in SEASONS} for v in names}
    dec = decide(per)
    lab = {"H0": "H0", "H1": "H1 (gewaehltes w)", "C": "Kontrolle (nur Streuung)"}
    for v, d in dec.items():
        out.append(f"  {lab[v]}: Brier in allen Saisons kleiner: {'ja' if d['Brier'] else 'nein'}; Log-Loss: {'ja' if d['LL'] else 'nein'}; Luecke ab 80 % kleiner: {'ja' if d['Luecke80'] else 'nein'}; Regel erfuellt: {'JA' if d['Regel'] else 'NEIN'}")
    out.append("  Gruppe ab 10 Spielen identisch zu R: " + ("ja" if all(store[("ab 10 Spielen", v, c)]["m"] == store[("ab 10 Spielen", "R", c)]["m"] for v in names for c in cols) else "NEIN"))
    out += ["", "4. JE w (Gruppe 1-9, Brier / Log-Loss je Testsaison, w fest, Parameter wie gewaehlt)"]
    for fam, fl in (("H1", "H1"), ("C", "Kontrolle")):
        for w in WS:
            cells = []
            for t in SEASONS:
                k, kmin, _ = folds[t]
                idx, P = p_of(f"{fam}_{w}", "1-9 Spiele", [t], (k, kmin))
                m = metrics(P.ravel(), hit[idx].ravel())
                cells.append(f"{m['brier']:.5f}/{m['ll']:.5f}")
            out.append(f"  {fl} w={w}: " + "   ".join(f"{t} {c}" for t, c in zip(SEASONS, cells)))
    out += ["", "5. NICHT GEPRUEFT", "  Signifikanz (nur Zeilenzahlen je Stufe, die Zeilen eines Spiels sind abhaengig); andere Wege der Spreizung (zum Beispiel breiterer Glaettungskern); Zeitgewichtung; getrennte Parameter fuer Starter und Bank;",
            "  Wirkung auf Teamabgleich und App; Verlauf nur ab 2023-24 (Gruppe 1-9 ist in 2023-24 grossteils der Saisonanfang)."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pbp-dir", default=str(HOME / "NBAEdge_pbp"))
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    ap.add_argument("--tmp", default=str(Path(tempfile.gettempdir()) / "minutes_empirical"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    text = run(Path(a.pbp_dir), Path(a.cache_dir), Path(a.tmp))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

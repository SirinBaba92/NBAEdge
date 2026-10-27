"""
Schwellwert-Test fuer Team-Maerkte (NUR MESSEN, keine Wettempfehlung, keine Aenderung am Produktivmodell). Baut auf analysis/backtest_team_round2.py (Ctx: Replay, Modell-Mittelwerte), backtest_team_markets.py auf.
Schreibt nur analysis/results/backtest_team_thresholds.json und .txt; Zwischenergebnisse ausserhalb des Projekts (--stage-dir, Standard /tmp/nbaedge_thresholds). Kein Netz.
Teil 4 (--real-days) liest KOPIEN von data/tracking/projection_snapshots.json nach /tmp (nie am Original).

Tipps (nur die Seiten, auf die gewettet wird):
- Sieger: Favorit (hoehere Siegchance, lp.win_prob_home(round(Spread,1)), 3-97 % begrenzt), Tipp "Favorit gewinnt"; ein Tipp je Spiel.
- Total Over und Team Total Over (Heim und Gast getrennt): Hauptlinie = naechste halbe Linie zum Modell-Mittelwert (floor(Mittelwert) + 0,5) und die 1 bis 5 Linien darunter (je 1 Punkt tiefer, Over wird
  wahrscheinlicher). Modell-Chance = 1 - Phi((Linie - Mittelwert) / Sigma) mit Sigma 18,6 (Total) bzw. 11,6 (Team Total). Es gibt keine historischen Linien: die Linien sind ein RASTER um das Modell.
- Schwellen t = 50, 55, ..., 90 %: zaehlt jeder Tipp mit Modell-Chance >= t (kumulativ).
Je Markt/Zeilengruppe/Schwelle: Tipps, richtig, falsch, Trefferquote, mittlere Modell-Chance, Differenz (Treffer minus Modell) in PP, Bootstrap-Intervall nach SPIELEN (1000 Ziehungen; alle Zeilen eines Spiels
bleiben zusammen), Anteil Saisons (mit mindestens 30 Tipps) mit Treffer >= Modell. Urteil "zu sicher" nur, wenn das Intervall der Differenz ganz unter 0 liegt, "zu vorsichtig" wenn ganz ueber 0.
Kalibrierung gut (Regel): mittlere Abweichung < 3 PP und keine Stufe (5-PP-Stufen der Tipp-Chance, ab 100 Zeilen) mehr als 6 PP daneben, bezogen auf alle Tipps ab Schwelle t.
Stabile Schwelle: die niedrigste bewertbare Schwelle t (mindestens 7 von 9 Saisons mit >= 30 Tipps), fuer die bei t UND allen hoeheren BEWERTBAREN Schwellen in JEDER Saison mit mindestens 30 Tipps die Trefferquote >=
mittlere Modell-Chance ist (nicht bewertbare Schwellen werden uebersprungen). Tipps pro Spieltag = Tipps / Zahl der Spieltage (Kalendertage mit Spielen) sowie je 9 Spiele.
EINSCHRAENKUNGEN: keine historischen Quoten (nur Trefferquote und Kalibrierung, keine Gewinnrechnung); Linien = Raster um das Modell; Zeilen eines Spiels korreliert (Bootstrap nach Spielen); Konstanten/Sigmas
teils auf denselben Saisons abgestimmt; reines Modell ohne Markt-Mischung (die App mischt den Markt ein).
Aufruf (von aussen mit nice -n 15):  venv/bin/python analysis/backtest_team_thresholds.py --all    --real-days (nur Teil 4)   --report   --selftest
"""
import json
import shutil
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.special import ndtr

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_team_round2 as r2  # noqa: E402
from backtest_team_markets import predicted_side_bins, lp  # noqa: E402
from config.settings import MIN_WIN_PROB, MAX_WIN_PROB  # noqa: E402

ROOT = HERE.parent
RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_team_thresholds.json", "backtest_team_thresholds.txt"
THRESH = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
MARKETS = {"win": "Sieger (Favorit gewinnt)", "total": "Total Over", "tt": "Team Total Over (Heim+Gast)"}
SUBSETS = ("alle", "haupt", "unter1", "unter2", "unter3", "unter4", "unter5")
MIN_SEASON_TIPS = 30
B_BOOT = 1000


def pr(x, d=3):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


# ----------------------------------------------------------------------------------------------- Tipp-Zeilen
class Rows:
    """Alle moeglichen Tipps: Arrays market (0 win, 1 total, 2 tt), game (Index), season, off (0..5), p, hit."""

    def __init__(self, market, game, season, off, p, hit, n_games):
        self.market, self.game, self.season, self.off, self.p, self.hit, self.n_games = (np.asarray(market), np.asarray(game), np.asarray(season), np.asarray(off), np.asarray(p), np.asarray(hit), n_games)


MCODE = {"win": 0, "total": 1, "tt": 2}


def build_hist(ctx):
    n = ctx.n
    gi = np.arange(n)
    pw = np.clip(ndtr(np.round(ctx.mu_s, 1) / lp.SPREAD_SIGMA), MIN_WIN_PROB, MAX_WIN_PROB)
    fav_home = pw >= 0.5
    ptip = np.where(fav_home, pw, 1 - pw)
    hit = np.where(fav_home, ctx.margin > 0, ctx.margin < 0).astype(float)
    M, G, S, O, P, H = [np.zeros(n, int)], [gi], [ctx.season], [np.zeros(n, int)], [ptip], [hit]
    for code, mus, xs, sig in ((1, [ctx.mu_t], [ctx.total], lp.TOTAL_SIGMA), (2, [ctx.mu_h, ctx.mu_a], [ctx.pts_h, ctx.pts_a], lp.TEAM_TOTAL_SIGMA)):
        for mu, x in zip(mus, xs):
            base = np.floor(mu) + 0.5
            for j in range(6):
                L = base - j
                M.append(np.full(n, code)); G.append(gi); S.append(ctx.season); O.append(np.full(n, j))
                P.append(1 - ndtr((L - mu) / sig)); H.append((x > L).astype(float))
    return Rows(np.concatenate(M), np.concatenate(G), np.concatenate(S), np.concatenate(O), np.concatenate(P), np.concatenate(H), n)


# ----------------------------------------------------------------------------------------------- Statistik
def subset_mask(R, market, sub):
    m = R.market == MCODE[market]
    if sub == "alle":
        return m
    j = 0 if sub == "haupt" else int(sub[-1])
    return m & (R.off == j)


def group_arrays(R, mask):
    g = R.game[mask]
    n = np.bincount(g, minlength=R.n_games).astype(float)
    h = np.bincount(g, weights=R.hit[mask], minlength=R.n_games)
    p = np.bincount(g, weights=R.p[mask], minlength=R.n_games)
    return n, h, p


def stat(R, mask, idx=None):
    n, h, p = group_arrays(R, mask)
    N = n.sum()
    if N == 0:
        return {"tipps": 0}
    out = {"tipps": int(N), "richtig": int(h.sum()), "falsch": int(N - h.sum()), "trefferquote_pct": pr(100 * h.sum() / N, 2), "mittel_modell_pct": pr(100 * p.sum() / N, 2), "differenz_pp": pr(100 * (h.sum() - p.sum()) / N, 2)}
    if idx is not None and N >= 20:
        d = 100 * (h[idx].sum(1) - p[idx].sum(1)) / np.maximum(n[idx].sum(1), 1)
        lo, hi = np.percentile(d, [2.5, 97.5])
        out["ci95_pp"] = [pr(lo, 2), pr(hi, 2)]
        out["urteil"] = "zu sicher" if hi < 0 else ("zu vorsichtig" if lo > 0 else "im Rahmen")
    return out


def table(R, idx, with_seasons=True, seasons=None):
    res = {}
    for market in MARKETS:
        subs = ("alle", "haupt", "unter1", "unter2", "unter3", "unter4", "unter5") if market != "win" else ("alle",)
        res[market] = {}
        for sub in subs:
            base = subset_mask(R, market, sub)
            res[market][sub] = {}
            for t in THRESH:
                m = base & (R.p >= t - 1e-12)
                cell = {"gepoolt": stat(R, m, idx)}
                if with_seasons:
                    per = {}
                    for s in seasons:
                        per[str(s)] = stat(R, m & (R.season == s))
                    ev = [v for v in per.values() if v["tipps"] >= MIN_SEASON_TIPS]
                    cell["saisons"] = per
                    cell["saisons_bewertet"] = len(ev)
                    cell["anteil_saisons_treffer_ge_modell"] = pr(sum(1 for v in ev if v["differenz_pp"] >= 0) / len(ev), 3) if ev else None
                res[market][sub][f"{int(round(t * 100))}"] = cell
    return res


def cal_rule(R, market, sub):
    """Kalibrierungsregel je Schwelle (kumulativ) auf Basis der 5-PP-Stufen der Tipp-Chance."""
    m = subset_mask(R, market, sub)
    p, y = R.p[m], R.hit[m]
    bins = predicted_side_bins(p, y)
    out = {}
    for t in THRESH:
        sel = [b for b in bins if float(b["stufe"].split("-")[0].replace("+", "").split()[0]) / 100.0 >= t - 1e-9]
        n = sum(b["n"] for b in sel)
        if n < 100:
            out[f"{int(round(t * 100))}"] = {"n": n, "pruefbar": False}
            continue
        mad = sum(b["n"] * abs(b["abweichung_pp"]) for b in sel) / n
        mx = max((abs(b["abweichung_pp"]) for b in sel if b["n"] >= 100), default=0.0)
        out[f"{int(round(t * 100))}"] = {"n": n, "pruefbar": True, "mittlere_abweichung_pp": pr(mad, 2), "max_stufe_ab100_pp": pr(mx, 2), "gut": bool(mad < 3 and mx <= 6)}
    return out, bins


def stable_threshold(tab, market, sub):
    """Niedrigste Schwelle t, ab der in jeder bewerteten Saison die Trefferquote >= Modell ist (siehe Kopf)."""
    cells = tab[market][sub]
    ok_from = None
    for t in reversed(THRESH):
        c = cells[f"{int(round(t * 100))}"]
        ev = [v for v in c["saisons"].values() if v["tipps"] >= MIN_SEASON_TIPS]
        if c["saisons_bewertet"] < 7:                       # zu wenige Tipps je Saison: Schwelle nicht bewertbar, nicht als Fehlschlag gezaehlt
            continue
        if all(v["differenz_pp"] >= 0 for v in ev):
            ok_from = t
        else:
            break
    return ok_from


# ----------------------------------------------------------------------------------------------- Auswertung historisch
def run_hist(stage):
    t0 = time.time()
    ctx = r2.Ctx()
    R = build_hist(ctx)
    seasons = sorted(set(ctx.season.tolist()))
    idx = np.random.default_rng(11).integers(0, R.n_games, (B_BOOT, R.n_games)).astype(np.int32)
    tab = table(R, idx, True, seasons)
    days = len(set(ctx.dates))
    out = {"teil": 1, "spiele": ctx.n, "spieltage": days, "saisons": seasons, "spiele_je_saison": {str(s): int((ctx.season == s).sum()) for s in seasons}, "tabelle": tab, "kalibrierung": {}, "stabil": {}}
    for market in MARKETS:
        for sub in tab[market]:
            cr, bins = cal_rule(R, market, sub)
            out["kalibrierung"].setdefault(market, {})[sub] = cr
            t = stable_threshold(tab, market, sub)
            cell = tab[market][sub][f"{int(round(t * 100))}"]["gepoolt"] if t else None
            out["stabil"].setdefault(market, {})[sub] = {"schwelle_pct": int(round(t * 100)) if t else None, "tipps": cell["tipps"] if cell else None,
                                                         "tipps_pro_spieltag": pr(cell["tipps"] / days, 2) if cell else None, "tipps_pro_9_spiele": pr(9 * cell["tipps"] / ctx.n, 2) if cell else None,
                                                         "trefferquote_pct": cell["trefferquote_pct"] if cell else None, "mittel_modell_pct": cell["mittel_modell_pct"] if cell else None}
    out["tipps_gesamt"] = {m: int((R.market == MCODE[m]).sum()) for m in MARKETS}
    out["laufzeit_s"] = round(time.time() - t0)
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "teil_hist.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"historische Tabelle fertig nach {time.time() - t0:.0f} s", flush=True)
    return out


# ----------------------------------------------------------------------------------------------- Teil 4: echte Tage
def real_days(src_dir, tmp_dir=Path("/tmp/nbaedge_thresholds_copy"), since="2026-10-22"):
    """Wiederholbar: kopiert projection_snapshots.json nach tmp_dir und wertet Spiele ab `since` mit Ergebnis aus (letzte Version vor Anpfiff, App-Chancen MIT Markt-Mischung, Sigmas der Version)."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_dir / "projection_snapshots.json", tmp_dir / "projection_snapshots.json")
    snaps = json.loads((tmp_dir / "projection_snapshots.json").read_text())["games"]
    M, G, O, P, H = [], [], [], [], []
    gi = 0
    used = 0
    sig_seen = set()
    for key, g in snaps.items():
        res = g.get("result") or {}
        if not res or g["game_date"] < since:
            continue
        start = datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")).timestamp()
        vers = [v for v in g["versions"] if datetime.fromisoformat(v["saved_at"]).timestamp() < start]
        if not vers:
            continue
        v = vers[-1]
        pj, sg = v["projection"], v.get("sigmas") or {}
        hp, ap = res["home_points"], res["away_points"]
        sig_seen.add((sg.get("spread"), sg.get("total"), sg.get("team_total")))
        used += 1
        pw = float(pj["home_win_prob"])
        fav_home = pw >= 0.5
        M.append(0); G.append(gi); O.append(0); P.append(pw if fav_home else 1 - pw); H.append(float((hp > ap) if fav_home else (ap > hp)))
        for code, mu, x, sigma in ((1, pj["exp_total"], hp + ap, sg.get("total", lp.TOTAL_SIGMA)), (2, pj["home_score"], hp, sg.get("team_total", lp.TEAM_TOTAL_SIGMA)), (2, pj["away_score"], ap, sg.get("team_total", lp.TEAM_TOTAL_SIGMA))):
            base = np.floor(mu) + 0.5
            for j in range(6):
                L = base - j
                M.append(code); G.append(gi); O.append(j); P.append(float(1 - ndtr((L - mu) / sigma))); H.append(float(x > L))
        gi += 1
    R = Rows(M, G, [0] * len(M), O, P, H, max(gi, 1))
    idx = np.random.default_rng(12).integers(0, R.n_games, (B_BOOT, R.n_games)).astype(np.int32)
    tab = table(R, idx, False)
    out = {"warnung": "KLEINE STICHPROBE, NUR INFORMATION: wenige Spiele, Zeilen eines Spiels korreliert, Intervalle breit; die Chancen sind die ANGEZEIGTEN App-Chancen (mit Markt-Mischung, Sigmas der Version) - nicht das reine Modell. "
                      "Linien = Raster um den App-Mittelwert (keine Betano-Linien).", "spiele": used, "sigmas_der_versionen": sorted(str(s) for s in sig_seen), "tabelle": tab}
    return out


def mode_real(stage):
    out = real_days(ROOT / "data" / "tracking")
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "teil_real.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"echte Tage: {out['spiele']} Spiele")
    return out


# ----------------------------------------------------------------------------------------------- Bericht
def cell_txt(c):
    g = c["gepoolt"]
    if g["tipps"] == 0:
        return "0 Tipps"
    ci = g.get("ci95_pp")
    return f"{g['tipps']} Tipps {g['richtig']}/{g['falsch']} richtig/falsch, Treffer {g['trefferquote_pct']:.1f} % gegen Modell {g['mittel_modell_pct']:.1f} % ({g['differenz_pp']:+.1f} PP" + (f" [{ci[0]:+.1f}; {ci[1]:+.1f}] {g['urteil']}" if ci else "") + ")"


def summary(H, Rl, runtime):
    L = ["ZUSAMMENFASSUNG Schwellwert-Test (nur Messung: KEINE Wettempfehlung, KEINE Änderung am Modell; reines Modell ohne Markt-Mischung, Regular Season 2017-18..2025-26, Linien = Raster um das Modell, keine historischen Quoten)",
         f"Daten: {H['spiele']} Spiele, {H['spieltage']} Spieltage; Tipps gesamt (alle Schwellen ab 50 %): " + ", ".join(f"{MARKETS[m]} {v}" for m, v in H["tipps_gesamt"].items()) + ". Stabile Schwelle = ab ihr (und höher) trifft in JEDER Saison (>= 30 Tipps) die Quote mindestens so oft wie das Modell sagt."]
    for m in MARKETS:
        st = H["stabil"][m]
        a, h = st["alle"], st["haupt"] if "haupt" in st else None
        txt = f"{MARKETS[m]}: stabil ab " + (f"{a['schwelle_pct']} % ({a['tipps']} Tipps = {a['tipps_pro_spieltag']} je Spieltag, {a['tipps_pro_9_spiele']} je 9 Spiele; Treffer {a['trefferquote_pct']} % gegen Modell {a['mittel_modell_pct']} %)" if a["schwelle_pct"] else "keine Schwelle (alle Zeilen)")
        if h:
            txt += "; nur Hauptlinie: " + (f"ab {h['schwelle_pct']} % ({h['tipps']} Tipps = {h['tipps_pro_spieltag']} je Spieltag; Treffer {h['trefferquote_pct']} % gegen {h['mittel_modell_pct']} %)" if h["schwelle_pct"] else "keine Schwelle")
        L.append(txt + ".")
    for m in MARKETS:
        c = H["tabelle"][m]["alle"]
        have = [t for t, x in c.items() if x["gepoolt"]["tipps"] >= 100]
        L.append(f"  {MARKETS[m]} (alle Zeilen) gepoolte Differenz PP / Anteil Saisons mit Treffer >= Modell je Schwelle: " + "; ".join(f"{t} %: {c[t]['gepoolt']['differenz_pp']:+.1f} / {'-' if c[t]['anteil_saisons_treffer_ge_modell'] is None else str(round(100 * c[t]['anteil_saisons_treffer_ge_modell'])) + ' %'}" for t in have) + f" (höchste Schwelle mit Tipps: {max(map(int, have))} %).")
    for m in MARKETS:
        tab = H["tabelle"][m]
        sure = []
        for sub, cells in tab.items():
            ts = [t for t, c in cells.items() if c["gepoolt"].get("urteil") == "zu sicher"]
            if ts:
                sure.append(f"{sub} ab {min(map(int, ts))} %")
        coverage = H["kalibrierung"][m]["alle"]
        ok = [t for t, c in coverage.items() if c.get("gut")]
        L.append(f"{MARKETS[m]}: zu sicher (Intervall der Differenz ganz unter 0): " + ("; ".join(sure) if sure else "nirgends") + f". Kalibrierungsregel (alle Zeilen) erfüllt bei Schwellen: {', '.join(ok) if ok else 'keiner'} % (geprüfte Schwellen mit >= 100 Tipps).")
    # Beispiel: Tabelle Sieger und Total (alle Zeilen) bei 60/70/80
    for m in ("win", "total", "tt"):
        c = H["tabelle"][m]["alle"]
        L.append(f"  {MARKETS[m]} (alle Zeilen) ab 60 %: " + cell_txt(c["60"]) + " | ab 70 %: " + cell_txt(c["70"]) + " | ab 80 %: " + cell_txt(c["80"]))
    if Rl:
        L.append(f"ECHTE TAGE ({Rl['spiele']} Spiele ab 22.10.2026; KLEINE STICHPROBE, NUR INFORMATION, App-Chancen mit Markt-Mischung): " + " | ".join(f"{MARKETS[m]} ab 60 %: {cell_txt(Rl['tabelle'][m]['alle']['60'])}" for m in MARKETS) + ".")
    L.append(f"Einschränkungen: keine historischen Quoten (nur Trefferquote/Kalibrierung, keine Gewinnrechnung); Linien als Raster um das Modell (Linien unter der Hauptlinie erzeugen die hohen Chancen); Zeilen eines Spiels korreliert (Bootstrap nach Spielen); Sigmas/Parameter teils auf denselben Saisons abgestimmt. Laufzeit {runtime:.0f} s.")
    return L


def render(H, Rl, runtime):
    L = summary(H, Rl, runtime)
    L += ["", "=" * 130, "Schwellwert-Test: Details. Format je Zeile: Tipps, richtig/falsch, Trefferquote gegen mittlere Modell-Chance (Differenz PP [95 %-Intervall nach Spielen] Urteil)", "=" * 130, ""]
    L += ["1. TABELLEN (gemeinsam 2017-18..2025-26, kumulativ ab Schwelle)"]
    for m, name in MARKETS.items():
        for sub, cells in H["tabelle"][m].items():
            L += [f"  {name} · Zeilen: {sub}"]
            for t, c in cells.items():
                a = c["anteil_saisons_treffer_ge_modell"]
                L.append(f"    ab {t:>2} %: {cell_txt(c)}; Saisons mit Treffer >= Modell: {'-' if a is None else f'{100 * a:.0f} %'} (von {c['saisons_bewertet']} bewerteten)")
    L += ["", "2. KALIBRIERUNG (Regel: mittl. Abweichung < 3 PP, keine Stufe >= 100 Zeilen > 6 PP; kumulativ ab Schwelle)"]
    for m, name in MARKETS.items():
        for sub, cr in H["kalibrierung"][m].items():
            L.append(f"  {name} · {sub}: " + " | ".join(f"ab {t} %: " + (f"{c['mittlere_abweichung_pp']} PP / max {c['max_stufe_ab100_pp']} PP {'gut' if c['gut'] else 'NICHT gut'} (n {c['n']})" if c.get("pruefbar") else f"n {c['n']} nicht prüfbar") for t, c in cr.items()))
    L += ["", "3. STABILITÄT (Schwelle, ab der in jeder Saison Treffer >= Modell; Tipps pro Spieltag)"]
    for m, name in MARKETS.items():
        for sub, st in H["stabil"][m].items():
            L.append(f"  {name} · {sub}: " + (f"ab {st['schwelle_pct']} %: {st['tipps']} Tipps, {st['tipps_pro_spieltag']} je Spieltag, {st['tipps_pro_9_spiele']} je 9 Spiele, Treffer {st['trefferquote_pct']} % gegen Modell {st['mittel_modell_pct']} %" if st["schwelle_pct"] else "keine solche Schwelle"))
    L += ["", "3b. Differenz Treffer minus Modell (PP) je Saison, Zeilen 'alle', Schwellen 60/70/80 %"]
    for m, name in MARKETS.items():
        for t in ("60", "70", "80"):
            c = H["tabelle"][m]["alle"][t]
            L.append(f"  {name} ab {t} %: " + ", ".join(f"{s}: {v['differenz_pp']:+.1f} (n {v['tipps']})" for s, v in c["saisons"].items() if v["tipps"] > 0))
    if Rl:
        L += ["", "4. ECHTE TAGE: " + Rl["warnung"], f"  Spiele: {Rl['spiele']}; Sigmas der Versionen (Spread, Total, Team Total): {Rl['sigmas_der_versionen']}"]
        for m, name in MARKETS.items():
            for sub, cells in Rl["tabelle"][m].items():
                if sub in ("alle", "haupt"):
                    L.append(f"  {name} · {sub}: " + " | ".join(f"ab {t} %: {cell_txt(c)}" for t, c in cells.items() if c["gepoolt"]["tipps"] > 0))
    return "\n".join(L) + "\n"


def report(stage, t0=None):
    t0 = t0 or time.time()
    H = json.loads((stage / "teil_hist.json").read_text())
    Rl = json.loads((stage / "teil_real.json").read_text()) if (stage / "teil_real.json").exists() else None
    runtime = time.time() - t0 + H.get("laufzeit_s", 0)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps({"version": 1, "hinweis": "Schwellwert-Test: nur Messung, keine Wettempfehlung.", "historisch": H, "echte_tage": Rl, "laufzeit_s": round(runtime)}, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render(H, Rl, runtime), encoding="utf-8")
    print("\n".join(summary(H, Rl, runtime)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}")
    return 0


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    ctx = r2.Ctx()
    R = build_hist(ctx)
    check("Tipps: Sieger = 1 je Spiel, Total 6 je Spiel, Teamtotal 12 je Spiel", (R.market == 0).sum() == ctx.n and (R.market == 1).sum() == 6 * ctx.n and (R.market == 2).sum() == 12 * ctx.n)
    check("Sieger-Tipp-Chance >= 50 %", R.p[R.market == 0].min() >= 0.5 - 1e-12)
    m = (R.market == 1) & (R.off == 0)
    check("Hauptlinie: Over-Chance nahe 50 % (Mittel 45..55)", 0.45 < R.p[m].mean() < 0.55, R.p[m].mean())
    check("Linie j unter der Hauptlinie: Over-Chance steigt", R.p[(R.market == 1) & (R.off == 3)].mean() > R.p[(R.market == 1) & (R.off == 0)].mean())
    idx = np.random.default_rng(1).integers(0, R.n_games, (200, R.n_games)).astype(np.int32)
    s = stat(R, (R.market == 1) & (R.p >= 0.5), idx)
    check("Statistik: richtig + falsch = Tipps", s["richtig"] + s["falsch"] == s["tipps"])
    check("Kumulativ: hoehere Schwelle -> weniger Tipps", stat(R, (R.market == 1) & (R.p >= 0.8))["tipps"] < stat(R, (R.market == 1) & (R.p >= 0.6))["tipps"])
    rd = real_days(ROOT / "data" / "tracking", Path("/tmp/nbaedge_thresholds_copy_selftest"))
    check("Echte Tage liefern Spiele", rd["spiele"] > 0, rd["spiele"])
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv
    stage = Path(a[a.index("--stage-dir") + 1]) if "--stage-dir" in a else Path("/tmp/nbaedge_thresholds")
    if "--selftest" in a:
        sys.exit(selftest())
    if "--real-days" in a:
        mode_real(stage); sys.exit(0)
    if "--report" in a:
        sys.exit(report(stage))
    if "--all" in a:
        t0 = time.time()
        run_hist(stage)
        mode_real(stage)
        sys.exit(report(stage, t0))
    print(__doc__)

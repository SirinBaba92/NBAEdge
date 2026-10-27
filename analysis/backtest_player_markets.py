"""
Spieler-Backtest (Walk-forward) fuer 2024-25 und 2025-26: P(Punkte >= k) der Spielerprognose (engine/player_forecast.py) gegen die tatsaechlichen Punkte. NUR LESEND aus data/cache, kein Netz;
schreibt nur analysis/results/backtest_player.json und analysis/results/backtest_player.txt. Produktivcode und bestehende Dateien bleiben unveraendert.

Aufruf (aus dem Projektordner):
  venv/bin/python analysis/backtest_player_markets.py --pilot          Probelauf: 2025-26, erste 30 Spieltage (schreibt nichts)
  venv/bin/python analysis/backtest_player_markets.py                  voller Lauf (Standard: Produktiv-league_ppm), danach Vergleich league_ppm kausal an 20 Spieltagen
  venv/bin/python analysis/backtest_player_markets.py --league-ppm-causal   voller Lauf mit league_ppm nur aus Zeilen vor dem Spieltag
  venv/bin/python analysis/backtest_player_markets.py --selftest

Aufbau: analysis/bt_player_adapter.py (Verlauf nur vor Spieltag D, Kader aus den Spielerzeilen, forecast_player/team_match mit historischen Eingaben). Spread/Total vor jedem Spiel: kausaler Team-Replay
(replica_tunable, Produktivparameter) und engine.projection.compute_projection OHNE Markt-Mischung. Teamergebnisse/Overtime: games_2023/2024/2025.json, Verbindung ueber Datum + Heim/Gast (Kuerzel).
Varianten: A roh | B Teamabgleich, Ausfaelle unbekannt | C Teamabgleich, Ausfaelle bekannt (OBERGRENZE: Rotationsspieler mit 0 Minuten werden als Ausfaelle uebergeben).
Meilensteine ohne Betano-Linien: alle ganzzahligen k mit 5 % <= P(Punkte >= k) <= 95 % der jeweiligen Variante (Auswahl nur aus der Prognose). Bewertet werden nur Spieler mit > 0 Minuten ("wenn er spielt").
Bootstrap IMMER nach Spielen. EINSCHRAENKUNGEN: Konstanten des Produktivmodells (BLOWOUT_CURVE/BLOWOUT_REF_SIGMA aus 2025-26, league_ppm 2025-26, Sigmas aus 2017-2025) sind fuer 2025-26 teils in-sample
und fuer 2024-25 "aus der Zukunft"; Ausfaelle sind nicht bekannt (B) bzw. nur nachtraeglich bekannt (C); Overtime wird nicht modelliert; Offseason-Wechsel sind am Saisonanfang im Kader unbekannt.
Reine Beschreibung, keine Empfehlungen zu Produktivparametern.
"""
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, ndtr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_team_markets as btm  # noqa: E402
from backtest_team_multiseason import ot_flags  # noqa: E402
import bt_player_adapter as bpa  # noqa: E402
from bt_player_adapter import Adapter, HistoryStore, p_array  # noqa: E402
from engine import line_probabilities as lp  # noqa: E402
from engine import player_forecast as pf  # noqa: E402
from engine.projection import compute_projection  # noqa: E402

CACHE = HERE.parent / "data" / "cache"
RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_player.json", "backtest_player.txt"
FILES = {"2023-24": "backtest_player_games_2023-24.json", "2024-25": "backtest_player_games_2024-25.json", "2025-26": "player_games_2025-26.json"}
EVAL = {"2024-25": 2024, "2025-26": 2025}                 # Saison -> Feld "season" der games_*.json
VARS = ("A", "B", "C")
VNAME = {"A": "A roh", "B": "B Teamabgleich, Ausfälle unbekannt", "C": "C Teamabgleich, Ausfälle bekannt (Obergrenze)"}
P_LO, P_HI = 0.05, 0.95
NAIVE_SIGMA = 6.0
B_BOOT = 400
MAD_MAX_PP, DEV_MAX_PP, MIN_ROWS = 3.0, 6.0, 100
PRODUCTION = btm.PRODUCTION


def th(n):
    """Tausenderpunkt (deutsch)."""
    return f"{int(n):,}".replace(",", ".")


def pr(x, d=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


# ----------------------------------------------------------------------------------------------- Daten
def load_rows():
    rows = {}
    for s, f in FILES.items():
        d = json.loads((CACHE / f).read_text(encoding="utf-8"))
        assert d["season"] == s, f
        rows[s] = d["rows"]
    return rows


def prepare_games(store_rows, season, games, replay):
    """Spiele der Saison (aus den Spielerzeilen) mit Teamprognose (Spread/Total vor dem Spiel), echtem Ergebnis, Overtime. Rueckgabe Liste chronologisch + Kontrollzahlen."""
    btm.SEASON = EVAL[season]
    d = btm.prepare(games, replay)
    d["ot"] = ot_flags(games, d["idx"])
    rs = np.where(d["post"] == 0)[0]
    bdl = {}
    for i in rs:
        g = games[d["idx"][i]]
        bdl[(g["date"][:10], g["home_team"]["abbreviation"], g["visitor_team"]["abbreviation"])] = int(i)
    by_game = defaultdict(list)
    for r in store_rows:
        by_game[r["game_id"]].append(r)
    out, ctl = [], Counter()
    for gid, rows in by_game.items():
        r0 = next((r for r in rows if r["home"]), None)
        date = rows[0]["date"]
        if r0 is None:                                             # neutraler Spielort (Paris, Mexiko, Cup-Finalrunde): Spielerzeilen ohne Heim-Kennzeichen -> Zuordnung wie in games_*.json (BDL)
            t = sorted({r["team"] for r in rows})
            if len(t) != 2:
                ctl["nicht_verbunden"] += 1
                continue
            home, away = next(((h, a) for h, a in ((t[0], t[1]), (t[1], t[0])) if (date, h, a) in bdl), (None, None))
            if home is None:
                ctl["nicht_verbunden"] += 1
                continue
            ctl["neutraler_ort_heim_aus_bdl"] += 1
        else:
            home, away = r0["team"], r0["opponent"]
        i, swapped = bdl.get((date, home, away)), False
        if i is None and (date, away, home) in bdl:
            i, swapped = bdl[(date, away, home)], True
        if i is None:
            ctl["nicht_verbunden"] += 1
            continue
        ctl["vertauscht"] += int(swapped)
        pts = defaultdict(int)
        for r in rows:
            pts[r["team"]] += r["points"]
        hp, ap = pts[home], pts[away]                              # Teampunkte aus den Spielerzeilen (auch beim Punktefehler POR/GSW)
        g = games[d["idx"][i]]
        pred = {"home_team": g["home_team"]["full_name"], "away_team": g["visitor_team"]["full_name"], "home_elo": float(replay["diff"][d["idx"][i]]), "away_elo": 0.0,
                "expected_total": float(replay["total_pred"][d["idx"][i]]), "home_win_prob": 0.5, "away_win_prob": 0.5}
        proj = compute_projection(pred, market_total=None, market_spread=None, game_date=date, is_playoff=False)
        sp, tot = proj["exp_spread"], proj["exp_total"]
        hs, as_ = proj["home_score"], proj["away_score"]
        if swapped:                                                # BDL fuehrt Heim/Gast vertauscht: Sicht des tatsaechlichen Heimteams
            sp, hs, as_ = -sp, as_, hs
        out.append({"game_id": gid, "date": date, "home": home, "away": away, "ctx": {"found": True, "exp_spread": sp, "exp_total": tot, "home_score": float(hs), "away_score": float(as_)},
                    "rows": rows, "ot": int(d["ot"][i]), "margin": hp - ap, "swapped": swapped})
    out.sort(key=lambda x: (x["date"], x["game_id"]))
    ctl["spiele_in_datei"] = len(by_game); ctl["spiele_ausgewertet"] = len(out)
    return out, dict(ctl)


def naive_mu(store, pid, day):
    """Saisonschnitt der Punkte (nur Spiele mit Minuten > 0 vor day): laufende Saison ab 5 Spielen, sonst Verlauf (laufende + Vorsaison) ab 5 Spielen, sonst None."""
    h = [r for r in store.history(pid, day) if r["minutes"] > 0]
    cur = store.season_of(day)
    c = [r["points"] for r in h if r["season"] == cur]
    if len(c) >= 5:
        return float(np.mean(c))
    a = [r["points"] for r in h]
    return float(np.mean(a)) if len(a) >= 5 else None


# ----------------------------------------------------------------------------------------------- Lauf
class Acc:
    """Sammelt Spielerzeilen (pg) und Meilenstein-Zeilen je Variante fuer eine Saison."""

    def __init__(self):
        self.pg = defaultdict(list)
        self.rows = {v: defaultdict(list) for v in VARS}
        self.n_pg = 0
        self.info = defaultdict(float)
        self.skipped = 0
        self.played_total = 0
        self.players = set()
        self.naive_mu = []

    def add(self, g, side, rec, store, day):
        r = rec["row"]
        i = self.n_pg
        self.n_pg += 1
        gi = g["gi"]
        home_flag = (side == "home")
        pgd = {"game": gi, "home": int(home_flag), "ot": g["ot"], "abs_margin": abs(g["margin"]), "team_gp": g["gp"][side], "half": g["half"], "min": r["minutes"], "pts": r["points"], "pid": rec["person_id"],
               "in_rot_B": int(rec["in_rot_B"]), "in_rot_C": int(rec["in_rot_C"])}
        for v in VARS:
            fc = rec["variants"][v]
            pgd[f"emin_{v}"], pgd[f"epts_{v}"] = fc["minutes"]["mean"], fc["expected_points"]
        for k, val in pgd.items():
            self.pg[k].append(val)
        self.naive_mu.append(naive_mu(store, rec["person_id"], day))
        self.players.add(rec["person_id"])
        for v in VARS:
            p = p_array(rec["variants"][v])
            m = (p >= P_LO) & (p <= P_HI)
            ks = np.nonzero(m)[0] + 1
            if len(ks):
                R = self.rows[v]
                R["pg"].append(np.full(len(ks), i, np.int32)); R["k"].append(ks.astype(np.int16)); R["p"].append(p[m]); R["y"].append((r["points"] >= ks).astype(np.int8))

    def arrays(self):
        pg = {k: np.asarray(v) for k, v in self.pg.items()}
        pg["naive_mu"] = np.array([np.nan if x is None else x for x in self.naive_mu])
        rows = {}
        for v in VARS:
            R = self.rows[v]
            rows[v] = {k: (np.concatenate(R[k]) if R[k] else np.array([])) for k in ("pg", "k", "p", "y")}
        return pg, rows


def run_season(season, games_season, store, adapter, days=None, log=True):
    """Alle Spiele (chronologisch) der Saison durch den Adapter. days: Menge erlaubter Spieltage (Pilot/Stichprobe) oder None."""
    acc = Acc()
    n_games = len(games_season)
    gp = defaultdict(int)
    half_cut = n_games // 2
    t0 = time.time()
    done = 0
    for gi, g in enumerate(games_season):
        g["gi"] = gi
        g["half"] = int(gi >= half_cut)
        g["gp"] = {"home": gp[g["home"]], "away": gp[g["away"]]}
        gp[g["home"]] += 1; gp[g["away"]] += 1
        if days is not None and g["date"] not in days:
            continue
        day = g["date"]
        adapter.set_day(day, (g["home"], g["away"]))
        for side, team, is_home in (("home", g["home"], True), ("away", g["away"], False)):
            ctx = g["ctx"] if is_home else {**g["ctx"], "exp_spread": g["ctx"]["exp_spread"]}
            played_rows = [r for r in g["rows"] if r["team"] == team and r["minutes"] > 0]
            if not played_rows:
                continue
            out, info = adapter.forecast_team(team, is_home, ctx, day, played_rows)
            acc.played_total += len(played_rows)
            acc.skipped += info["skipped"]
            for k in ("roster", "rotation_B", "absent"):
                acc.info[k] += info[k]
            acc.info["matched_B"] += int(info["matched_B"]); acc.info["matched_C"] += int(info["matched_C"]); acc.info["team_games"] += 1
            if info["factor_B"] is not None:
                acc.info["factor_B_sum"] += info["factor_B"]; acc.info["factor_B_n"] += 1
            for rec in out:
                acc.add(g, side, rec, store, day)
        done += 1
        if log and done % 100 == 0:
            print(f"  {season}: {done} Spiele, {acc.n_pg} Spielerzeilen, {time.time() - t0:.0f} s", flush=True)
    return acc


# ----------------------------------------------------------------------------------------------- Kennzahlen
def group_sums(gid, w, G):
    return np.bincount(gid, weights=w, minlength=G)


def boot_ratio(num_g, den_g, B=B_BOOT, seed=0):
    """Summe(num)/Summe(den) mit Bootstrap ueber Gruppen (Spiele)."""
    G = len(num_g)
    est = num_g.sum() / den_g.sum() if den_g.sum() else np.nan
    if G < 5:
        return est, np.nan, np.nan
    idx = np.random.default_rng(seed).integers(0, G, (B, G))
    r = num_g[idx].sum(axis=1) / np.maximum(den_g[idx].sum(axis=1), 1e-12)
    return float(est), float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


def bin_aggregates(game_of_row, p, y, G):
    """(G, 20)-Summen je Spiel und 5-PP-Stufe: Anzahl, Summe p, Summe y."""
    b = np.minimum((p * 20).astype(int), 19)
    key = game_of_row.astype(np.int64) * 20 + b
    n = np.bincount(key, minlength=G * 20).reshape(G, 20).astype(float)
    sp = np.bincount(key, weights=p, minlength=G * 20).reshape(G, 20)
    sy = np.bincount(key, weights=y, minlength=G * 20).reshape(G, 20)
    return n, sp, sy


def binned_slope(n, sp, sy):
    """Kalibrierungs-Steigung aus Stufenmitteln (gewichtete Logistik auf logit(mittleres p))."""
    ok = n > 0
    pb, yb, nb = (sp[ok] / n[ok]), (sy[ok] / n[ok]), n[ok]
    if len(pb) < 4:
        return None
    z = np.log(np.clip(pb, 1e-6, 1 - 1e-6) / (1 - np.clip(pb, 1e-6, 1 - 1e-6)))
    f = lambda b: float(-(nb * (yb * np.log(np.clip(expit(b[0] + b[1] * z), 1e-9, 1)) + (1 - yb) * np.log(np.clip(1 - expit(b[0] + b[1] * z), 1e-9, 1)))).sum() / nb.sum())
    return float(minimize(f, [0.0, 1.0], method="BFGS").x[1])


def calibration(game_of_row, p, y, G, B=200, seed=1):
    n, sp, sy = bin_aggregates(game_of_row, p, y, G)
    N, SP, SY = n.sum(0), sp.sum(0), sy.sum(0)
    idx = np.random.default_rng(seed).integers(0, G, (B, G))
    bs_dev = np.full((B, 20), np.nan)
    bs_slope = []
    for t in range(B):
        nn, ss, yy = n[idx[t]].sum(0), sp[idx[t]].sum(0), sy[idx[t]].sum(0)
        with np.errstate(invalid="ignore", divide="ignore"):
            bs_dev[t] = 100 * (yy / nn - ss / nn)
        if t < 100:
            s = binned_slope(nn, ss, yy)
            if s is not None:
                bs_slope.append(s)
    bins = []
    for b in range(20):
        if N[b] > 0:
            lo, hi = np.nanpercentile(bs_dev[:, b], [2.5, 97.5]) if np.isfinite(bs_dev[:, b]).any() else (np.nan, np.nan)
            bins.append({"stufe": f"{5 * b}-{5 * b + 5} %", "n": int(N[b]), "modell": pr(SP[b] / N[b]), "treffer": pr(SY[b] / N[b]), "abweichung_pp": pr(100 * (SY[b] / N[b] - SP[b] / N[b]), 2), "ci95_pp": [pr(lo, 2), pr(hi, 2)]})
    s_point = binned_slope(N, SP, SY)
    return bins, s_point, ([pr(np.percentile(bs_slope, 2.5), 3), pr(np.percentile(bs_slope, 97.5), 3)] if len(bs_slope) > 10 else None)


def coverage(bins):
    big = [b for b in bins if b["n"] >= MIN_ROWS]
    tot = sum(b["n"] for b in bins)
    mad = sum(b["n"] * abs(b["abweichung_pp"]) for b in bins) / tot if tot else None
    bad = [b["stufe"] for b in big if abs(b["abweichung_pp"]) > DEV_MAX_PP]
    good = [b["stufe"] for b in big if abs(b["abweichung_pp"]) <= DEV_MAX_PP]
    rng = lambda lo, hi: [b for b in bins if lo <= int(b["stufe"].split("-")[0]) < hi]
    sub = {}
    for name, (lo, hi) in {"niedrig 5-35 %": (5, 35), "mittel 35-65 %": (35, 65), "hoch 65-95 %": (65, 95)}.items():
        bb = rng(lo, hi)
        t = sum(b["n"] for b in bb)
        m = sum(b["n"] * abs(b["abweichung_pp"]) for b in bb) / t if t else None
        mx = max((abs(b["abweichung_pp"]) for b in bb if b["n"] >= MIN_ROWS), default=0.0)
        sub[name] = {"n": t, "mittlere_abweichung_pp": pr(m, 2), "max_abweichung_pp_ab100": pr(mx, 2), "gedeckt": bool(t >= MIN_ROWS and m is not None and m < MAD_MAX_PP and mx <= DEV_MAX_PP)}
    return {"gedeckt_insgesamt": bool(mad is not None and mad < MAD_MAX_PP and not bad), "mittlere_abweichung_pp": pr(mad, 2), "stufen_ueber_6pp": bad, "stufen_gedeckt_ab100": good, "bereiche": sub}


def row_metrics(R, pgg, G, with_ci=True):
    """Brier, Log-Loss, Treffer, mittleres p, Steigung (Zeilenebene) fuer die Zeilen R (dict pg,p,y) mit Spiel-Index je Zeile."""
    p, y = R["p"], R["y"].astype(float)
    gr = pgg[R["pg"]]
    if len(p) == 0:
        return {"n": 0}
    loss_b, loss_l = (p - y) ** 2, btm.ll(p, y)
    cnt = group_sums(gr, np.ones(len(p)), G)
    b = boot_ratio(group_sums(gr, loss_b, G), cnt, seed=2) if with_ci else (loss_b.mean(), np.nan, np.nan)
    l = boot_ratio(group_sums(gr, loss_l, G), cnt, seed=3) if with_ci else (loss_l.mean(), np.nan, np.nan)
    h = y.mean()
    return {"n": int(len(p)), "brier": pr(b[0]), "brier_ci95": [pr(b[1]), pr(b[2])], "logloss": pr(l[0]), "logloss_ci95": [pr(l[1]), pr(l[2])], "mittel_modell": pr(p.mean()), "trefferquote": pr(h),
            "abweichung_pp": pr(100 * (h - p.mean()), 2), "brier_basisrate": pr(h * (1 - h)), "steigung": pr(btm.slope_fit(p, y), 3)}


def point_metrics(emin, epts, amin, apts, pg_game, G):
    out = {}
    for name, e, a in (("minuten", emin, amin), ("punkte", epts, apts)):
        err = e - a
        cnt = group_sums(pg_game, np.ones(len(err)), G)
        bias = boot_ratio(group_sums(pg_game, err, G), cnt, seed=4)
        mae = boot_ratio(group_sums(pg_game, np.abs(err), G), cnt, seed=5)
        out[name] = {"n": int(len(err)), "bias": pr(bias[0], 3), "bias_ci95": [pr(bias[1], 3), pr(bias[2], 3)], "mae": pr(mae[0], 3), "mae_ci95": [pr(mae[1], 3), pr(mae[2], 3)]}
    return out


def role_bias(emin, amin, pg_game, G):
    out = {}
    for name, m in (("unter 20 Min", emin < 20), ("20-28 Min", (emin >= 20) & (emin <= 28)), ("ueber 28 Min", emin > 28)):
        if m.sum() < 30:
            out[name] = {"n": int(m.sum())}
            continue
        err = (emin - amin)[m]
        gg = pg_game[m]
        cnt = group_sums(gg, np.ones(len(err)), G)
        bb = boot_ratio(group_sums(gg, err, G), cnt, seed=6)
        out[name] = {"n": int(m.sum()), "bias": pr(bb[0], 3), "bias_ci95": [pr(bb[1], 3), pr(bb[2], 3)], "mae": pr(np.abs(err).mean(), 3), "mittel_erwartet": pr(emin[m].mean(), 2), "mittel_tatsaechlich": pr(amin[m].mean(), 2)}
    return out


def slice_masks(pg):
    """Aufteilungen auf Ebene der Spielerzeilen (pg)."""
    ex = {v: pg[f"epts_{v}"] for v in VARS}
    return {"heim": pg["home"] == 1, "gast": pg["home"] == 0, "grosser_abstand_ab_15": pg["abs_margin"] >= 15, "enges_spiel_bis_6": pg["abs_margin"] <= 6, "mit_overtime": pg["ot"] == 1, "ohne_overtime": pg["ot"] == 0,
            "erste_15_teamspiele": pg["team_gp"] < 15, "rest_der_saison": pg["team_gp"] >= 15, "erste_haelfte": pg["half"] == 0, "zweite_haelfte": pg["half"] == 1}


def season_report(acc, pilot=False):
    pg, rows = acc.arrays()
    G = int(pg["game"].max()) + 1 if len(pg["game"]) else 0
    rep = {"spielerzeilen": int(acc.n_pg), "spiele": G, "spieler": len(acc.players), "uebersprungene_spieler": int(acc.skipped), "anteil_uebersprungen": pr(acc.skipped / max(1, acc.played_total), 4),
           "gespielte_spieler_gesamt": int(acc.played_total), "team_spiele": int(acc.info["team_games"]), "kader_ø": pr(acc.info["roster"] / max(1, acc.info["team_games"]), 2), "rotation_B_ø": pr(acc.info["rotation_B"] / max(1, acc.info["team_games"]), 2),
           "ausfaelle_C_ø_je_teamspiel": pr(acc.info["absent"] / max(1, acc.info["team_games"]), 2), "teamabgleich_gelungen_B": pr(acc.info["matched_B"] / max(1, acc.info["team_games"]), 3),
           "faktor_f_B_ø": pr(acc.info["factor_B_sum"] / max(1, acc.info["factor_B_n"]), 3), "varianten": {}}
    for v in VARS:
        R = rows[v]
        gr = pg["game"][R["pg"]]
        m = row_metrics(R, pg["game"], G)
        bins, s_b, s_ci = calibration(gr, R["p"], R["y"].astype(float), G)
        m["stufen"], m["steigung_stufen"], m["steigung_stufen_ci95"] = bins, pr(s_b, 3), s_ci
        m["abdeckung"] = coverage(bins)
        m["punktfehler"] = point_metrics(pg[f"emin_{v}"], pg[f"epts_{v}"], pg["min"], pg["pts"], pg["game"], G)
        m["minuten_nach_rolle"] = role_bias(pg[f"emin_{v}"], pg["min"], pg["game"], G)
        sl = {}
        for name, mk in slice_masks(pg).items():
            sel = mk[R["pg"]]
            sub = {"pg": R["pg"][sel], "p": R["p"][sel], "y": R["y"][sel]}
            sl[name] = {k: v for k, v in row_metrics(sub, pg["game"], G, with_ci=False).items() if k in ("n", "brier", "mittel_modell", "trefferquote", "abweichung_pp")}
        for name, mk in {"rolle_unter_20_min": pg[f"emin_{v}"] < 20, "rolle_20_28_min": (pg[f"emin_{v}"] >= 20) & (pg[f"emin_{v}"] <= 28), "rolle_ueber_28_min": pg[f"emin_{v}"] > 28,
                         "erwartete_punkte_unter_10": pg[f"epts_{v}"] < 10, "erwartete_punkte_10_20": (pg[f"epts_{v}"] >= 10) & (pg[f"epts_{v}"] <= 20), "erwartete_punkte_ueber_20": pg[f"epts_{v}"] > 20}.items():
            sel = mk[R["pg"]]
            sub = {"pg": R["pg"][sel], "p": R["p"][sel], "y": R["y"][sel]}
            sl[name] = {k: v for k, v in row_metrics(sub, pg["game"], G, with_ci=False).items() if k in ("n", "brier", "mittel_modell", "trefferquote", "abweichung_pp")}
        m["aufteilungen"] = sl
        rep["varianten"][v] = m
    # Naiver Vergleich auf den Zeilen von A (Saisonschnitt des Spielers, fester Normalverteilungs-Streuwert)
    RA = rows["A"]
    mu = pg["naive_mu"][RA["pg"]]
    ok = np.isfinite(mu)
    pn = 1.0 - ndtr((RA["k"][ok] - 0.5 - mu[ok]) / NAIVE_SIGMA)
    y = RA["y"][ok].astype(float)
    gr = pg["game"][RA["pg"][ok]]
    la, ln = (RA["p"][ok] - y) ** 2, (pn - y) ** 2
    cnt = group_sums(gr, np.ones(len(y)), G)
    d = boot_ratio(group_sums(gr, ln - la, G), cnt, seed=7)
    rep["naiv"] = {"beschreibung": f"p = 1 - Phi((k - 0,5 - Saisonschnitt) / {NAIVE_SIGMA}); Saisonschnitt = Punkte des Spielers in der laufenden Saison vor D (ab 5 Spielen, sonst Verlauf ab 5 Spielen), fester Streuwert",
                   "n": int(ok.sum()), "anteil_von_A": pr(ok.mean(), 3), "brier_naiv": pr(ln.mean()), "brier_A_gleiche_zeilen": pr(la.mean()), "differenz_naiv_minus_A": pr(d[0]), "differenz_ci95": [pr(d[1]), pr(d[2])], "steigung_naiv": pr(btm.slope_fit(pn, y), 3)}
    # Varianten-Vergleich auf gemeinsamen Zeilen (Spiel, Spieler, k)
    keyA = rows["A"]["pg"].astype(np.int64) * 64 + rows["A"]["k"]
    comp = {}
    for v in ("B", "C"):
        keyV = rows[v]["pg"].astype(np.int64) * 64 + rows[v]["k"]
        _, ia, iv = np.intersect1d(keyA, keyV, return_indices=True)
        pa, pv, yy = rows["A"]["p"][ia], rows[v]["p"][iv], rows["A"]["y"][ia].astype(float)
        gg = pg["game"][rows["A"]["pg"][ia]]
        diff = (pv - yy) ** 2 - (pa - yy) ** 2
        cnt = group_sums(gg, np.ones(len(diff)), G)
        bd = boot_ratio(group_sums(gg, diff, G), cnt, seed=8)
        comp[f"{v}_minus_A"] = {"gemeinsame_zeilen": int(len(diff)), "brier_A": pr(((pa - yy) ** 2).mean()), f"brier_{v}": pr(((pv - yy) ** 2).mean()), "differenz": pr(bd[0], 5), "ci95": [pr(bd[1], 5), pr(bd[2], 5)],
                                "zeilen_nur_in_A": int(len(keyA) - len(ia)), "zeilen_nur_in_" + v: int(len(keyV) - len(iv))}
    rep["varianten_vergleich"] = comp
    return rep, (pg, rows)


# ----------------------------------------------------------------------------------------------- Kontrollen
def direct_checks(store, all_rows, seasons_games, adapter, n=5, seed=11):
    """Mindestens 5 zufaellige Spiele: Adapter-Ergebnis (Variante A) gegen direkten Aufruf von forecast_player mit unabhaengig gefilterten historischen Eingaben."""
    rng = random.Random(seed)
    pool = [g for s in seasons_games.values() for g in s]
    res = []
    for g in rng.sample(pool, n):
        day = g["date"]
        adapter.set_day(day, (g["home"], g["away"]))
        for r in rng.sample([r for r in g["rows"] if r["minutes"] > 0], 3):
            cur = pf.ph.season_of_date(day)
            keep = (cur, bpa.prev_season(cur))
            brute = [x for x in all_rows if x["person_id"] == r["person_id"] and x["date"] < day and x["season"] in keep]
            is_home = r["team"] == g["home"]
            spread = g["ctx"]["exp_spread"] if is_home else g["ctx"]["exp_spread"]
            direct = bpa.ORIG_FORECAST(r["person_id"], day, home=is_home, exp_spread=spread, exp_total=g["ctx"]["exp_total"], games=brute, name=r["name"])
            via = adapter.forecast_player(r["person_id"], day, home=is_home, exp_spread=spread, exp_total=g["ctx"]["exp_total"], name=r["name"])
            same = direct["ok"] == via["ok"] and (not direct["ok"] or (np.array_equal(p_array(direct), p_array(via)) and direct["expected_points"] == via["expected_points"]))
            res.append({"spiel": g["game_id"], "datum": day, "spieler": r["name"], "identisch": bool(same), "verlauf_zeilen": len(brute)})
    return {"ok": all(x["identisch"] for x in res), "stichproben": res}


# ----------------------------------------------------------------------------------------------- Text
def tier_text(m):
    """Kurzbeschreibung der Kalibrierung nach Bereichen (Treffer minus Modell in PP)."""
    parts = []
    for name, rng in (("5-20 %", (5, 20)), ("20-50 %", (20, 50)), ("50-80 %", (50, 80)), ("80-95 %", (80, 95))):
        bb = [b for b in m["stufen"] if rng[0] <= int(b["stufe"].split("-")[0]) < rng[1]]
        n = sum(b["n"] for b in bb)
        if n:
            dev = sum(b["n"] * b["abweichung_pp"] for b in bb) / n
            parts.append(f"{name}: {dev:+.1f} PP")
    return ", ".join(parts)


def verdict(m):
    s, ci = m["steigung_stufen"], m["steigung_stufen_ci95"]
    if s is None or not ci:
        return "Steigung nicht bestimmbar"
    if ci[1] < 1:
        return f"zu sicher (Steigung {s:.2f} [{ci[0]:.2f}; {ci[1]:.2f}])"
    if ci[0] > 1:
        return f"zu vorsichtig (Steigung {s:.2f} [{ci[0]:.2f}; {ci[1]:.2f}])"
    return f"Steigung {s:.2f} [{ci[0]:.2f}; {ci[1]:.2f}], 1 liegt im Intervall"


def summary_lines(rep):
    L = []
    both = rep["beide"]
    seasons = [s for s in rep["saisons"]]
    n_rows = {v: both["varianten"][v]["n"] for v in VARS}
    L.append(f"ZUSAMMENFASSUNG Spieler-Backtest (Walk-forward, Saisons {', '.join(seasons)}; nur Spieler mit > 0 Minuten, Meilensteine k mit 5-95 % Modell-Chance, keine Betano-Linien). Zeilen A/B/C: "
             f"{th(n_rows['A'])}/{th(n_rows['B'])}/{th(n_rows['C'])}; Spielerzeilen {th(both['spielerzeilen'])}; übersprungene Spieler (ohne Verlauf) {100 * both['anteil_uebersprungen']:.1f} %.")
    L.append("EINSCHRÄNKUNGEN: Blowout-Kurve, league_ppm (2025-26) und Sigmas sind für 2025-26 teils in-sample, für 2024-25 aus der Zukunft. Ausfälle unbekannt (B) bzw. nachträglich bekannt (C = OBERGRENZE). Overtime nicht modelliert. Reines Team-Modell ohne Markt.")
    for v in VARS:
        m = both["varianten"][v]
        L.append(f"{VNAME[v]}: Brier {m['brier']:.4f} [{m['brier_ci95'][0]:.4f}; {m['brier_ci95'][1]:.4f}] (Basisrate-Referenz {m['brier_basisrate']:.4f}), Log-Loss {m['logloss']:.4f}; Modell Ø {m['mittel_modell']:.3f} gegen Treffer {m['trefferquote']:.3f}; {verdict(m)}.")
        L.append(f"   nach Stufen (Treffer minus Modell): {tier_text(m)}; gedeckt (Ø Abweichung {m['abdeckung']['mittlere_abweichung_pp']} PP): {'ja' if m['abdeckung']['gedeckt_insgesamt'] else 'nein'}"
                 + (f", Stufen über 6 PP daneben: {', '.join(m['abdeckung']['stufen_ueber_6pp'])}" if m["abdeckung"]["stufen_ueber_6pp"] else "") + ".")
    nv = both["naiv"]
    L.append(f"Naiver Vergleich (Saisonschnitt, fester Streuwert {NAIVE_SIGMA:g}; auf {100 * nv['anteil_von_A']:.0f} % der A-Zeilen): Brier naiv {nv['brier_naiv']:.4f} gegen A {nv['brier_A_gleiche_zeilen']:.4f}, Differenz {nv['differenz_naiv_minus_A']:+.4f} [{nv['differenz_ci95'][0]:+.4f}; {nv['differenz_ci95'][1]:+.4f}].")
    for s in seasons:
        c = rep["saisons"][s]["varianten_vergleich"]
        L.append(f"Teamabgleich {s}: Brier B−A {c['B_minus_A']['differenz']:+.5f} [{c['B_minus_A']['ci95'][0]:+.5f}; {c['B_minus_A']['ci95'][1]:+.5f}], C−A {c['C_minus_A']['differenz']:+.5f} [{c['C_minus_A']['ci95'][0]:+.5f}; {c['C_minus_A']['ci95'][1]:+.5f}] (negativ = besser als roh; gemeinsame Zeilen).")
    for v in VARS:
        pm = both["varianten"][v]["punktfehler"]
        rb = both["varianten"][v]["minuten_nach_rolle"]
        L.append(f"{VNAME[v][:1]}: Minuten Bias {pm['minuten']['bias']:+.2f} (MAE {pm['minuten']['mae']:.2f}), Punkte Bias {pm['punkte']['bias']:+.2f} (MAE {pm['punkte']['mae']:.2f}); Minuten-Bias nach Rolle: "
                 + ", ".join(f"{k} {x['bias']:+.2f} (n {x['n']})" for k, x in rb.items() if "bias" in x) + ".")
    sl = both["varianten"]["B"]["aufteilungen"]
    big = sorted([(k, x) for k, x in sl.items() if x.get("n", 0) >= 5000], key=lambda kx: -abs(kx[1]["abweichung_pp"]))[:3]
    L.append("Größte Abweichungen Treffer minus Modell in Aufteilungen (B, n >= 5000): " + "; ".join(f"{k} {x['abweichung_pp']:+.1f} PP (Brier {x['brier']:.4f}, n {th(x['n'])})" for k, x in big) + ".")
    pc = rep.get("ppm_vergleich")
    if pc:
        L.append(f"league_ppm: Produktiv {pc['ppm_produktiv']:.4f} gegen kausal {pc['ppm_kausal_min']:.4f}-{pc['ppm_kausal_max']:.4f} (20 Spieltage 2025-26); Brier B {pc['brier_B_produktiv']:.4f} gegen {pc['brier_B_kausal']:.4f}, C {pc['brier_C_produktiv']:.4f} gegen {pc['brier_C_kausal']:.4f}.")
    L.append("Nur Beschreibung der Messung; keine Änderungen am Produktivmodell, keine Parameter-Empfehlungen.")
    return L


def fmt_table(rows, cols, head):
    w = [max(len(h), max((len(str(r[c])) for r in rows), default=0)) for c, h in zip(cols, head)]
    line = lambda vals: "  ".join(str(v).rjust(wi) for v, wi in zip(vals, w))
    return [line(head), line(["-" * wi for wi in w])] + [line([r[c] for c in cols]) for r in rows]


def render(rep, runtime):
    L = summary_lines(rep)
    L += ["", "=" * 120, f"Spieler-Backtest, Laufzeit {runtime:.0f} s. Rechenweg: Kopf von analysis/backtest_player_markets.py und analysis/bt_player_adapter.py.", "=" * 120, ""]
    c = rep["kontrollen"]
    L += ["KONTROLLEN", f"  Adapter gegen direkten Aufruf von forecast_player (Variante A, {len(c['direkt']['stichproben'])} Spieler in 5 Spielen): {'identisch' if c['direkt']['ok'] else 'ABWEICHUNG'}.",
          f"  Vergangenheits-Prüfung: Assertion 'Datum < Spieltag' für jede übergebene Zeile: {th(c['geprueft_zeilen'])} Zeilen in {th(c['aufrufe'])} Aufrufen, jüngste genutzte Zeile {c['juengste_zeile']}; keine Verletzung.",
          f"  Teamergebnisse verbunden (Datum + Heim/Gast): " + "; ".join(f"{s}: {x['spiele_ausgewertet']} von {x['spiele_in_datei']} (vertauscht {x.get('vertauscht', 0)}, nicht verbunden {x.get('nicht_verbunden', 0)})" for s, x in c["spiele"].items()), ""]
    for s in list(rep["saisons"]) + ["beide"]:
        r = rep["saisons"][s] if s != "beide" else rep["beide"]
        L += [f"=== {s} ===", f"  Spiele {r['spiele']}, Spielerzeilen {th(r['spielerzeilen'])}, Spieler {r.get('spieler', '-')}, übersprungen {r['uebersprungene_spieler']} ({100 * r['anteil_uebersprungen']:.1f} %)"]
        if s != "beide":
            L.append(f"  Kader Ø {r['kader_ø']}, Rotation Ø {r['rotation_B_ø']}, Ausfälle (C) Ø {r['ausfaelle_C_ø_je_teamspiel']} je Teamspiel, Teamabgleich gelungen {100 * r['teamabgleich_gelungen_B']:.0f} %, Faktor f Ø {r['faktor_f_B_ø']}")
        for v in VARS:
            m = r["varianten"][v]
            L += [f"  [{VNAME[v]}]  Zeilen {th(m['n'])}  Brier {m['brier']:.4f} [{m['brier_ci95'][0]:.4f}; {m['brier_ci95'][1]:.4f}]  Basisrate {m['brier_basisrate']:.4f}  Log-Loss {m['logloss']:.4f}  Modell Ø {m['mittel_modell']:.3f}  Treffer {m['trefferquote']:.3f}  Steigung {m['steigung']} (Stufen {m['steigung_stufen']})",
                  f"    Minuten Bias {m['punktfehler']['minuten']['bias']:+.2f} [{m['punktfehler']['minuten']['bias_ci95'][0]:+.2f}; {m['punktfehler']['minuten']['bias_ci95'][1]:+.2f}] MAE {m['punktfehler']['minuten']['mae']:.2f}; Punkte Bias {m['punktfehler']['punkte']['bias']:+.2f} [{m['punktfehler']['punkte']['bias_ci95'][0]:+.2f}; {m['punktfehler']['punkte']['bias_ci95'][1]:+.2f}] MAE {m['punktfehler']['punkte']['mae']:.2f}",
                  "    Minuten-Bias nach Rolle (erwartet): " + "; ".join(f"{k}: {x['bias']:+.2f} (n {x['n']}, erwartet Ø {x['mittel_erwartet']}, tatsächlich Ø {x['mittel_tatsaechlich']})" for k, x in m["minuten_nach_rolle"].items() if "bias" in x)]
            L += ["    Kalibrierung nach Stufen (Zeilen eines Spiels nicht unabhängig, Intervall nach Spielen):"] + ["      " + t for t in fmt_table([{**b, "ci": f"[{b['ci95_pp'][0]:+.1f}; {b['ci95_pp'][1]:+.1f}]"} for b in m["stufen"]], ["stufe", "n", "modell", "treffer", "abweichung_pp", "ci"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP", "95 %-Intervall"])]
            cv = m["abdeckung"]
            L += [f"    Abdeckung: Ø Abweichung {cv['mittlere_abweichung_pp']} PP, gedeckt insgesamt: {'ja' if cv['gedeckt_insgesamt'] else 'nein'}; Stufen mit >= 100 Zeilen über 6 PP daneben: {cv['stufen_ueber_6pp'] or 'keine'}; " + "; ".join(f"{k}: {'gedeckt' if x['gedeckt'] else 'nicht gedeckt'} (Ø {x['mittlere_abweichung_pp']} PP, n {x['n']})" for k, x in cv["bereiche"].items())]
            L += ["    Aufteilungen (n Zeilen / Brier / Treffer minus Modell in PP):"]
            for k, x in m["aufteilungen"].items():
                L.append(f"      {k:<28} {x['n']:>8}  {fp(x.get('brier'))}  {fp(x.get('abweichung_pp'), 1, True)}")
        L += ["  Vergleich der Varianten (gemeinsame Zeilen, Brier-Differenz, Intervall nach Spielen):"] + [f"    {k}: Differenz {x['differenz']:+.5f} [{x['ci95'][0]:+.5f}; {x['ci95'][1]:+.5f}] auf {th(x['gemeinsame_zeilen'])} Zeilen (Brier A {x['brier_A']:.4f}, {k[0]} {x['brier_' + k[0]]:.4f})" for k, x in r["varianten_vergleich"].items()]
        nv = r["naiv"]
        L += [f"  Naiv: Brier {nv['brier_naiv']:.4f} gegen A {nv['brier_A_gleiche_zeilen']:.4f} (n {th(nv['n'])}, Differenz {nv['differenz_naiv_minus_A']:+.4f} [{nv['differenz_ci95'][0]:+.4f}; {nv['differenz_ci95'][1]:+.4f}]); {nv['beschreibung']}", ""]
    return "\n".join(L) + "\n"


def fp(x, d=4, sign=False):
    return "-" if x is None else f"{x:{'+' if sign else ''}.{d}f}"


# ----------------------------------------------------------------------------------------------- Hauptprogramm
def setup():
    all_rows = load_rows()
    flat = [r for rows in all_rows.values() for r in rows]
    store = HistoryStore(flat)
    games = btm.load_games(2015, 2025)
    replay, _, _, _ = btm.rt.run(games, **PRODUCTION)
    return all_rows, flat, store, games, replay


def render_only():
    """Text neu aus backtest_player.json rendern (ohne Neuberechnung)."""
    rep = json.loads((RESULTS / OUT_JSON).read_text(encoding="utf-8"))
    (RESULTS / OUT_TXT).write_text(render(rep, rep["laufzeit_sekunden"]), encoding="utf-8")
    print("\n".join(summary_lines(rep)))
    return 0


def main():
    if "--render-only" in sys.argv:
        return render_only()
    t0 = time.time()
    pilot = "--pilot" in sys.argv
    causal = "--league-ppm-causal" in sys.argv
    all_rows, flat, store, games, replay = setup()
    adapter = Adapter(store, league_ppm_causal=causal)
    seasons = ["2025-26"] if pilot else list(EVAL)
    sg, ctl = {}, {}
    for s in seasons:
        sg[s], ctl[s] = prepare_games(all_rows[s], s, games, replay)
        print(f"{s}: {ctl[s]}", flush=True)
    reps, data = {}, {}
    for s in seasons:
        days = None
        if pilot:
            days = set(sorted({g["date"] for g in sg[s]})[:30])
        t1 = time.time()
        acc = run_season(s, sg[s], store, adapter, days)
        reps[s], data[s] = season_report(acc)
        print(f"{s}: {acc.n_pg} Spielerzeilen, Meilenstein-Zeilen A/B/C "
              f"{sum(len(x) for x in acc.rows['A']['p'])}/{sum(len(x) for x in acc.rows['B']['p'])}/{sum(len(x) for x in acc.rows['C']['p'])}, {time.time() - t1:.0f} s", flush=True)
    if pilot:
        r = reps["2025-26"]
        print(f"\nPILOT 2025-26, erste 30 Spieltage: {r['spiele']} Spiele, {r['spielerzeilen']} Spielerzeilen, Zeilen A/B/C {[r['varianten'][v]['n'] for v in VARS]}, Laufzeit {time.time() - t0:.0f} s (Rechenzeit Lauf {time.time() - t1:.0f} s)")
        for v in VARS:
            m = r["varianten"][v]
            print(f"  {VNAME[v]}: Brier {m['brier']} Modell {m['mittel_modell']} Treffer {m['trefferquote']} Steigung {m['steigung']}")
        print(f"  übersprungene Spieler {r['anteil_uebersprungen']}, Adapter-Prüfung Zeilen {adapter.checked_rows}, jüngste Zeile {adapter.max_date_seen}")
        return 0
    both = both_report(data, reps)
    rep = {"version": 1, "hinweis": "Walk-forward Spieler-Backtest; siehe Kopf von analysis/backtest_player_markets.py (Einschraenkungen: Konstanten in-sample/aus der Zukunft, Ausfaelle, OT).", "league_ppm": "kausal" if causal else "produktiv (2025-26)",
           "saisons": reps, "beide": both}
    seasons_games = sg
    ctrl = {"direkt": direct_checks(store, flat, seasons_games, adapter), "geprueft_zeilen": adapter.checked_rows, "aufrufe": adapter.calls, "juengste_zeile": adapter.max_date_seen, "spiele": ctl}
    rep["kontrollen"] = ctrl
    if not causal:
        rep["ppm_vergleich"] = ppm_compare(store, sg["2025-26"], flat)
    runtime = time.time() - t0
    rep["laufzeit_sekunden"] = round(runtime)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render(rep, runtime), encoding="utf-8")
    print("\n".join(summary_lines(rep)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}\nLaufzeit: {runtime:.0f} s")
    return 0


def both_report(data, reps):
    """Beide Saisons zusammen: Arrays verketten (Spiele-Index versetzen) und denselben Bericht rechnen."""
    pgs, rows_, off_g, off_pg = [], {v: [] for v in VARS}, 0, 0
    for s, (pg, rows) in data.items():
        pg2 = dict(pg)
        pg2["game"] = pg["game"] + off_g
        pgs.append(pg2)
        for v in VARS:
            r2 = dict(rows[v])
            r2["pg"] = rows[v]["pg"] + off_pg
            rows_[v].append(r2)
        off_g += int(pg["game"].max()) + 1
        off_pg += len(pg["game"])
    pg = {k: np.concatenate([p[k] for p in pgs]) for k in pgs[0]}
    rows = {v: {k: np.concatenate([r[k] for r in rows_[v]]) for k in ("pg", "k", "p", "y")} for v in VARS}
    rep = _report_from_arrays(pg, rows, data)
    sk, pl = sum(r["uebersprungene_spieler"] for r in reps.values()), sum(r["gespielte_spieler_gesamt"] for r in reps.values())
    rep["uebersprungene_spieler"], rep["gespielte_spieler_gesamt"], rep["anteil_uebersprungen"] = sk, pl, pr(sk / max(1, pl), 4)
    rep["team_spiele"] = sum(r["team_spiele"] for r in reps.values())
    return rep


def _report_from_arrays(pg, rows, data):
    class _A:
        pass
    a = _A()
    a.arrays = lambda: (pg, rows)
    a.n_pg = len(pg["game"]); a.info = defaultdict(float); a.skipped = 0; a.played_total = 0; a.players = set(pg["pid"].tolist())
    rep, _ = season_report(a)
    # Zaehler aus den Saisons addieren
    return rep


def ppm_compare(store, games_season, flat, n_days=20, seed=5):
    rng = random.Random(seed)
    days = sorted({g["date"] for g in games_season})
    sample = set(rng.sample(days, n_days))
    out = {}
    ppm_vals = []
    for causal in (False, True):
        ad = Adapter(store, league_ppm_causal=causal)
        acc = run_season("2025-26", [dict(g) for g in games_season], store, ad, sample, log=False)
        rep, _ = season_report(acc)
        out[causal] = rep
        if causal:
            ppm_vals = [store.ppm_before(d) for d in sample]
    return {"tage": sorted(sample), "ppm_produktiv": ad.prod_ppm, "ppm_kausal_min": min(ppm_vals), "ppm_kausal_max": max(ppm_vals),
            "brier_A": out[False]["varianten"]["A"]["brier"], "brier_B_produktiv": out[False]["varianten"]["B"]["brier"], "brier_B_kausal": out[True]["varianten"]["B"]["brier"],
            "brier_C_produktiv": out[False]["varianten"]["C"]["brier"], "brier_C_kausal": out[True]["varianten"]["C"]["brier"], "zeilen_B": out[False]["varianten"]["B"]["n"]}


def selftest_metrics() -> int:
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    rng = np.random.default_rng(2)
    G, per = 400, 50
    gid = np.repeat(np.arange(G), per)
    p = rng.uniform(0.05, 0.95, G * per)
    y = (rng.random(G * per) < p).astype(float)
    bins, s, ci = calibration(gid, p, y, G)
    cov = coverage(bins)
    check("kalibrierte Kunstdaten: Steigung nahe 1, 1 im Intervall, Abdeckung erfuellt", abs(s - 1) < 0.15 and ci[0] <= 1 <= ci[1] and cov["gedeckt_insgesamt"], (s, ci, cov["mittlere_abweichung_pp"]))
    y2 = (rng.random(G * per) < np.clip(0.5 + 0.6 * (p - 0.5), 0.01, 0.99)).astype(float)
    bins2, s2, ci2 = calibration(gid, p, y2, G)
    check("zu sicheres Modell: Steigung < 0.8, Abdeckung nicht erfuellt, Urteil 'zu sicher'", s2 < 0.8 and not coverage(bins2)["gedeckt_insgesamt"] and verdict({"steigung_stufen": s2, "steigung_stufen_ci95": ci2}).startswith("zu sicher"), (s2, ci2))
    n, sp, sy = bin_aggregates(gid, p, y, G)
    check("Stufen-Summen: Anzahl = Zeilen, Summe y = Treffer", int(n.sum()) == len(p) and abs(sy.sum() - y.sum()) < 1e-9 and abs(sp.sum() - p.sum()) < 1e-6)
    est, lo, hi = boot_ratio(np.bincount(gid, weights=(p - y) ** 2, minlength=G), np.full(G, float(per)), seed=1)
    check("Bootstrap nach Spielen: Schaetzer im Intervall, Breite > 0", lo < est < hi and hi - lo > 0, (est, lo, hi))
    kA = np.array([0 * 64 + 5, 0 * 64 + 6, 1 * 64 + 5], np.int64); kB = np.array([0 * 64 + 6, 1 * 64 + 5, 1 * 64 + 7], np.int64)
    _, ia, ib = np.intersect1d(kA, kB, return_indices=True)
    check("gemeinsame Zeilen (Spiel, Spieler, k) werden ueber den Schluessel gefunden", sorted(kA[ia]) == [6, 69] and len(ia) == 2)
    print("\nMETRIK-SELBSTTEST BESTANDEN" if ok else "\nMETRIK-SELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(bpa.selftest() | selftest_metrics())
    sys.exit(main())

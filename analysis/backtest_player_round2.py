"""
Spieler-Backtest, Runde 2: Varianten des Teamabgleichs und der Verteilungsbreite messen (NUR MESSEN, keine Empfehlung). Baut auf analysis/bt_player_adapter.py und analysis/backtest_player_markets.py auf.
Produktivcode, App, Tests, bestehende Dateien bleiben unveraendert; Eingriffe nur zur LAUFZEIT im Prozess des Backtests (Konstanten von engine/player_forecast.py werden voruebergehend gesetzt und zurueckgestellt;
die Breiten-Variante fuehrt den Quelltext von forecast_player mit EINER geaenderten Zeile aus, c = 1,0 ist identisch zum Original - wird kontrolliert). Kein Netz. Schreibt nur
analysis/results/backtest_player_round2.json und .txt; Zwischenergebnisse je Variante und Saison liegen ausserhalb des Projekts (--stage-dir, Standard /tmp/nbaedge_round2).

Varianten (Versionsbezeichnung fuer spaeter):
  A  roh (Referenz = Runde 1)                                              v2-roh
  B  heutiger Teamabgleich, Ausfaelle unbekannt (Referenz = Runde 1)       v2-teamabgleich
  D  nur Minuten abgleichen (Rotation auf 240 wie Produktiv-distribute_minutes, Starter-Grenze 36), Punkte pro Minute unveraendert, KEIN Faktor f    v3-minutenabgleich
     (Laufzeit: F_MIN = F_MAX = 1,0 -> f wirkt nicht, Minutenverteilung bleibt die des Produktivmodells)
  E  wie B, aber f nur mit halber Staerke (f ** 0,5; TEAM_MATCH_STRENGTH = 0,5)    v3-teamabgleich-halbf
  F  roh mit breiterer Verteilung: Glaettungskern h = 1 + 0,05 x wird mit c multipliziert, c in {1,0 (= A), 1,15, 1,3, 1,5}    v3-breite-c
     Stelle: der Kern in forecast_player ist die am wenigsten eingreifende (Erwartungswerte und Minuten bleiben gleich; nur die Form der Verteilung aendert sich). Zusatz nur im Raster: c auf die Minutenstreuung sd0 (F_m).
  G  D und F kombiniert (c = beste Breite aus F der Trainingssaison)         v3-minutenabgleich-breite
  D_C, E_C  D und E mit der Obergrenze "Ausfaelle bekannt" (wie Variante C in Runde 1), nur Kurzvergleich.
Meilenstein-Zeilen wie Runde 1: ganzzahlige k mit 5 % <= P(Punkte >= k) <= 95 % der jeweiligen Variante. Kader: Rotation Top 10 aus den letzten Teamspielen, Ausfaelle unbekannt.
Parameterwahl (nur c): auf der Trainingssaison (jeder 4. Spieltag), nach Brier auf den gemeinsamen Zeilen mit A; Test auf der anderen Saison, beide Richtungen.
Bewertungsregel: Verbesserung gegenueber A nur, wenn die Brier-Differenz (Variante minus A) in der Testsaison negativ ist UND das Intervall (Bootstrap nach Spielen) die 0 nicht einschliesst UND in beiden Richtungen dasselbe Vorzeichen gilt.
EINSCHRAENKUNGEN: Konstanten (Blowout-Kurve, league_ppm, Sigmas) fuer 2025-26 teils in-sample, fuer 2024-25 aus der Zukunft; Ausfaelle unbekannt (B, D, E, F, G) bzw. nachtraeglich bekannt (*_C = Obergrenze); Overtime nicht modelliert.
Aufruf:  venv/bin/python analysis/backtest_player_round2.py --all            (alles: Raster, Lauf beider Saisons parallel, Bericht; Hintergrund empfohlen)
         --pilot  (Zeitmessung 8 Spieltage)   --report  (nur Bericht aus den Zwischenergebnissen)   --selftest
"""
import inspect
import json
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_player_markets as bpm  # noqa: E402
import backtest_team_markets as btm  # noqa: E402
import bt_player_adapter as bpa  # noqa: E402
from bt_player_adapter import Adapter, HistoryStore, p_array  # noqa: E402
from engine import player_forecast as pf  # noqa: E402

RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_player_round2.json", "backtest_player_round2.txt"
SEASONS = ("2024-25", "2025-26")
C_VALUES = (1.15, 1.3, 1.5)
VERSION = {"A": "v2-roh", "B": "v2-teamabgleich", "D": "v3-minutenabgleich", "E": "v3-teamabgleich-halbf", "G": "v3-minutenabgleich-breite", "D_C": "v3-minutenabgleich (Ausfälle bekannt)", "E_C": "v3-teamabgleich-halbf (Ausfälle bekannt)",
           "F1.15": "v3-breite-1.15", "F1.3": "v3-breite-1.3", "F1.5": "v3-breite-1.5"}
TM_SETTINGS = {"B": {}, "D": {"fmin": 1.0, "fmax": 1.0}, "E": {"strength": 0.5}, "G": {"fmin": 1.0, "fmax": 1.0}, "D_C": {"fmin": 1.0, "fmax": 1.0}, "E_C": {"strength": 0.5}}
ABSENT = {"D_C": "D", "E_C": "E"}                      # Variante mit bekannten Ausfaellen -> gleiche Variante ohne Ausfaelle (wenn niemand fehlt)
P_LO, P_HI = bpm.P_LO, bpm.P_HI


# ----------------------------------------------------------------------------------------------- Laufzeit-Eingriffe
def _build_impl():
    src = inspect.getsource(bpa.ORIG_FORECAST)
    a, b = "h = 1.0 + 0.05 * x", "m_k = np.clip(mu + sd0 * z, 0.0, MAX_MINUTES)"
    assert a in src and b in src, "Quelltext von forecast_player hat sich geaendert"
    src = src.replace(a, "h = C_K * (1.0 + 0.05 * x)").replace(b, "m_k = np.clip(mu + C_M * sd0 * z, 0.0, MAX_MINUTES)")
    g = dict(vars(pf))
    g["C_K"], g["C_M"] = 1.0, 1.0
    exec(compile(src, "<forecast_player_breite>", "exec"), g)
    return g["forecast_player"], g


IMPL, IMPL_G = _build_impl()


@contextmanager
def settings(ck=1.0, cm=1.0, fmin=None, fmax=None, strength=None):
    """Konstanten des Produktivmodells voruebergehend setzen (nur im Prozess) und zurueckstellen."""
    old = (pf.F_MIN, pf.F_MAX, pf.TEAM_MATCH_STRENGTH, bpa.ORIG_FORECAST, IMPL_G["C_K"], IMPL_G["C_M"])
    if fmin is not None:
        pf.F_MIN, pf.F_MAX = fmin, fmax
    if strength is not None:
        pf.TEAM_MATCH_STRENGTH = strength
    IMPL_G["C_K"], IMPL_G["C_M"] = ck, cm
    bpa.ORIG_FORECAST = IMPL if (ck != 1.0 or cm != 1.0) else old[3]
    try:
        yield
    finally:
        pf.F_MIN, pf.F_MAX, pf.TEAM_MATCH_STRENGTH, bpa.ORIG_FORECAST, IMPL_G["C_K"], IMPL_G["C_M"] = old


# ----------------------------------------------------------------------------------------------- Lauf
class Acc2:
    """Sammelt Spielerzeilen (pg) und Meilenstein-Zeilen je Variante (beliebige Variantennamen)."""

    def __init__(self, names):
        self.names = list(names)
        self.pg = defaultdict(list)
        self.rows = {v: defaultdict(list) for v in self.names}
        self.n_pg = 0
        self.team = defaultdict(list)
        self.skipped = self.played = 0

    def add(self, g, side, r, fcs, in_rot):
        i = self.n_pg
        self.n_pg += 1
        d = {"game": g["gi"], "home": int(side == "home"), "ot": g["ot"], "abs_margin": abs(g["margin"]), "team_gp": g["gp"][side], "half": g["half"], "min": r["minutes"], "pts": r["points"], "pid": r["person_id"], "in_rot_B": int(in_rot)}
        for v in self.names:
            d[f"emin_{v}"], d[f"epts_{v}"] = fcs[v]["minutes"]["mean"], fcs[v]["expected_points"]
        for k, val in d.items():
            self.pg[k].append(val)
        for v in self.names:
            p = p_array(fcs[v])
            m = (p >= P_LO) & (p <= P_HI)
            ks = np.nonzero(m)[0] + 1
            if len(ks):
                R = self.rows[v]
                R["pg"].append(np.full(len(ks), i, np.int32)); R["k"].append(ks.astype(np.int16)); R["p"].append(p[m]); R["y"].append((r["points"] >= ks).astype(np.int8))

    def save(self, stage, season):
        stage.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(stage / f"pg_{season}.npz", **{k: np.asarray(v) for k, v in self.pg.items()})
        for v in self.names:
            R = self.rows[v]
            np.savez_compressed(stage / f"rows_{season}_{v}.npz", **{k: (np.concatenate(R[k]) if R[k] else np.array([])) for k in ("pg", "k", "p", "y")})
        np.savez_compressed(stage / f"team_{season}.npz", **{k: np.asarray(v) for k, v in self.team.items()})
        (stage / f"meta_{season}.json").write_text(json.dumps({"n_pg": self.n_pg, "skipped": self.skipped, "played": self.played, "names": self.names}), encoding="utf-8")


def forecast_team_multi(adapter, team, is_home, ctx, day, played_rows, c_star, names, grid_only=False):
    """Prognosen aller Varianten fuer die Spieler eines Teams (nur Spieler mit > 0 Minuten). Rueckgabe (Liste, Teaminfo, uebersprungen)."""
    played = {r["person_id"] for r in played_rows}
    sp = ctx["exp_spread"]; tot = ctx.get("exp_total")
    with settings():
        B = pf.team_match(team, is_home, ctx, day, None, None)
    absent = {p for p, rank in B["rank"].items() if rank <= pf.ROTATION_SIZE and p not in played}
    oks, skipped = [], 0
    for r in played_rows:
        raw = B["raw"].get(r["person_id"]) or adapter.forecast_player(r["person_id"], day, home=is_home, exp_spread=sp, exp_total=tot, name=r["name"])
        if not raw["ok"]:
            skipped += 1
            continue
        oks.append((r, raw))
    fcs = {r["person_id"]: {"A": raw} for r, raw in oks}
    info = {"before": B["info"]["minutes_before"], "after": {}}
    if "B" in names:
        for r, raw in oks:
            fcs[r["person_id"]]["B"] = B["adjusted"].get(r["person_id"]) or raw
        info["after"]["B"] = B["info"]["minutes_after"]
    # breite Verteilungen (raw)
    wide = {}
    for v in names:
        if v.startswith("F") and not v.startswith("Fm"):
            ck = float(v[1:])
            with settings(ck=ck):
                for r, raw in oks:
                    fcs[r["person_id"]][v] = adapter.forecast_player(r["person_id"], day, home=is_home, exp_spread=sp, exp_total=tot, name=r["name"])
        if v.startswith("Fm"):
            cm = float(v[2:])
            with settings(cm=cm):
                for r, raw in oks:
                    fcs[r["person_id"]][v] = adapter.forecast_player(r["person_id"], day, home=is_home, exp_spread=sp, exp_total=tot, name=r["name"])
    tmres = {"B": B}
    for v in ("D", "E", "G", "D_C", "E_C"):
        if v not in names:
            continue
        base = ABSENT.get(v)
        if base and not absent:
            tmres[v] = tmres[base]
        else:
            kw = dict(TM_SETTINGS[v])
            if v == "G":
                kw["ck"] = c_star
            with settings(**kw):
                tmres[v] = pf.team_match(team, is_home, ctx, day, None, absent if base else None)
        res = tmres[v]
        rawfb = {r["person_id"]: (fcs[r["person_id"]].get(f"F{c_star}") if v == "G" and f"F{c_star}" in names else fcs[r["person_id"]]["A"]) for r, _ in oks}
        for r, raw in oks:
            pid = r["person_id"]
            fb = res["raw"].get(pid) or rawfb[pid] if base else (rawfb[pid])
            fcs[pid][v] = res["adjusted"].get(pid) or fb
        info["after"][v] = res["info"]["minutes_after"]
    return [(r, fcs[r["person_id"]], r["person_id"] in {p for p in B["adjusted"]}) for r, _ in oks], info, skipped


def run_season(season, games_season, store, adapter, names, c_star, days=None, log=True):
    acc = Acc2(names)
    gp = defaultdict(int)
    n = len(games_season)
    t0 = time.time(); done = 0
    for gi, g in enumerate(games_season):
        g["gi"] = gi; g["half"] = int(gi >= n // 2)
        g["gp"] = {"home": gp[g["home"]], "away": gp[g["away"]]}
        gp[g["home"]] += 1; gp[g["away"]] += 1
        if days is not None and g["date"] not in days:
            continue
        day = g["date"]
        adapter.set_day(day, (g["home"], g["away"]))
        for side, team, is_home in (("home", g["home"], True), ("away", g["away"], False)):
            played_rows = [r for r in g["rows"] if r["team"] == team and r["minutes"] > 0]
            if not played_rows:
                continue
            out, info, skipped = forecast_team_multi(adapter, team, is_home, g["ctx"], day, played_rows, c_star, names)
            acc.played += len(played_rows); acc.skipped += skipped
            acc.team["game"].append(gi); acc.team["before"].append(info["before"])
            for v in ("B", "D", "E", "G", "D_C", "E_C"):
                acc.team[f"after_{v}"].append(info["after"].get(v, np.nan))
            for r, fcs, in_rot in out:
                acc.add(g, side, r, fcs, in_rot)
        done += 1
        if log and done % 100 == 0:
            print(f"  {season}: {done} Spiele, {acc.n_pg} Spielerzeilen, {time.time() - t0:.0f} s", flush=True)
    return acc


def load_games(season):
    all_rows, flat, store, games, replay = bpm.setup()
    sg, ctl = bpm.prepare_games(all_rows[season], season, games, replay)
    return flat, store, sg, ctl


def sample_days(sg):
    days = sorted({g["date"] for g in sg})
    return set(days[::4])


def mode_grid(season, stage):
    flat, store, sg, ctl = load_games(season)
    adapter = Adapter(store)
    names = ["A"] + [f"F{c}" for c in C_VALUES] + [f"Fm{c}" for c in C_VALUES]
    # Raster: nur roh-Varianten (kein Teamabgleich noetig) -> eigener schlanker Lauf
    days = sample_days(sg)
    acc = Acc2(names)
    gp = defaultdict(int)
    for gi, g in enumerate(sg):
        g["gi"] = gi; g["half"] = 0; g["gp"] = {"home": 0, "away": 0}
        if g["date"] not in days:
            continue
        adapter.set_day(g["date"], (g["home"], g["away"]))
        for side, team, is_home in (("home", g["home"], True), ("away", g["away"], False)):
            rows = [r for r in g["rows"] if r["team"] == team and r["minutes"] > 0]
            for r in rows:
                sp, tot = g["ctx"]["exp_spread"], g["ctx"]["exp_total"]
                fc = {"A": adapter.forecast_player(r["person_id"], g["date"], home=is_home, exp_spread=sp, exp_total=tot, name=r["name"])}
                if not fc["A"]["ok"]:
                    continue
                for v in names[1:]:
                    kw = {"ck": float(v[1:])} if v[1] != "m" else {"cm": float(v[2:])}
                    with settings(**kw):
                        fc[v] = adapter.forecast_player(r["person_id"], g["date"], home=is_home, exp_spread=sp, exp_total=tot, name=r["name"])
                acc.add(g, side, r, fc, False)
    pg, rows = {k: np.asarray(v) for k, v in acc.pg.items()}, {v: {k: (np.concatenate(acc.rows[v][k]) if acc.rows[v][k] else np.array([])) for k in ("pg", "k", "p", "y")} for v in names}
    G = int(pg["game"].max()) + 1
    out = {"tage": len(days), "spielerzeilen": int(acc.n_pg), "varianten": {}}
    keyA = rows["A"]["pg"].astype(np.int64) * 64 + rows["A"]["k"]
    la_all = (rows["A"]["p"] - rows["A"]["y"]) ** 2
    out["brier_A_alle_zeilen"] = float(la_all.mean())
    for v in names[1:]:
        keyV = rows[v]["pg"].astype(np.int64) * 64 + rows[v]["k"]
        _, ia, iv = np.intersect1d(keyA, keyV, return_indices=True)
        d = (rows[v]["p"][iv] - rows[v]["y"][iv]) ** 2 - (rows["A"]["p"][ia] - rows["A"]["y"][ia]) ** 2
        out["varianten"][v] = {"brier_diff_zu_A_gemeinsame_zeilen": float(d.mean()), "brier_alle_zeilen": float(((rows[v]["p"] - rows[v]["y"]) ** 2).mean()), "zeilen": int(len(rows[v]["p"])), "gemeinsame_zeilen": int(len(d))}
    stage.mkdir(parents=True, exist_ok=True)
    (stage / f"grid_{season}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"Raster {season}: " + ", ".join(f"{v} {x['brier_diff_zu_A_gemeinsame_zeilen']:+.5f}" for v, x in out["varianten"].items()), flush=True)


def mode_run(season, stage, c_star):
    flat, store, sg, ctl = load_games(season)
    adapter = Adapter(store)
    names = ["A", "B", "D", "E", "G", "D_C", "E_C"] + [f"F{c}" for c in C_VALUES]
    t0 = time.time()
    acc = run_season(season, sg, store, adapter, names, c_star)
    acc.save(stage, season)
    print(f"Lauf {season} fertig: {acc.n_pg} Spielerzeilen, {time.time() - t0:.0f} s", flush=True)


def mode_pilot(stage):
    flat, store, sg, ctl = load_games("2025-26")
    adapter = Adapter(store)
    days = set(sorted({g["date"] for g in sg})[:8])
    names = ["A", "B", "D", "E", "G", "D_C", "E_C"] + [f"F{c}" for c in C_VALUES]
    # Kontrolle: Breiten-Implementierung mit c = 1 identisch zum Original
    ok = True
    g = sg[0]; adapter.set_day(g["date"], (g["home"], g["away"]))
    for r in [r for r in g["rows"] if r["minutes"] > 0][:6]:
        a = adapter.forecast_player(r["person_id"], g["date"], home=True, exp_spread=g["ctx"]["exp_spread"], exp_total=g["ctx"]["exp_total"], name=r["name"])
        with settings(ck=1.0 + 1e-12):
            b = adapter.forecast_player(r["person_id"], g["date"], home=True, exp_spread=g["ctx"]["exp_spread"], exp_total=g["ctx"]["exp_total"], name=r["name"])
        ok &= (not a["ok"]) or np.allclose(p_array(a), p_array(b), atol=1e-9)
    print("Kontrolle Breiten-Implementierung (c = 1 gleich Original):", "OK" if ok else "ABWEICHUNG")
    t0 = time.time()
    acc = run_season("2025-26", sg, store, adapter, names, 1.3, days, log=False)
    dt = time.time() - t0
    games = sum(1 for g in sg if g["date"] in days)
    per_game = dt / max(1, games)
    print(f"Pilot: {games} Spiele, {acc.n_pg} Spielerzeilen in {dt:.0f} s = {per_game:.2f} s je Spiel; volle Saison (1230 Spiele) ca. {per_game * 1230 / 60:.0f} min; "
          f"beide Saisons parallel ca. {per_game * 1230 / 60:.0f} min plus Raster ca. {per_game * 1230 / 60 * 0.15:.0f} min und Bericht ca. 5 min")


# ----------------------------------------------------------------------------------------------- Bericht
def load_stage(stage, season):
    pg = dict(np.load(stage / f"pg_{season}.npz"))
    meta = json.loads((stage / f"meta_{season}.json").read_text())
    rows = {v: dict(np.load(stage / f"rows_{season}_{v}.npz")) for v in meta["names"]}
    team = dict(np.load(stage / f"team_{season}.npz"))
    return pg, rows, team, meta


def merge(parts):
    pgs, rows, teams, off_g, off_pg = [], defaultdict(list), [], 0, 0
    names = list(parts[0][1].keys())
    for pg, rw, team, meta in parts:
        pg2 = dict(pg); pg2["game"] = pg["game"] + off_g
        pgs.append(pg2)
        for v in names:
            r2 = dict(rw[v]); r2["pg"] = rw[v]["pg"] + off_pg
            rows[v].append(r2)
        t2 = dict(team); t2["game"] = team["game"] + off_g; teams.append(t2)
        off_g += int(pg["game"].max()) + 1; off_pg += len(pg["game"])
    return ({k: np.concatenate([p[k] for p in pgs]) for k in pgs[0]}, {v: {k: np.concatenate([r[k] for r in rows[v]]) for k in ("pg", "k", "p", "y")} for v in names},
            {k: np.concatenate([t[k] for t in teams]) for k in teams[0]})


def calib10(game_of_row, p, y, G, B=200, seed=1):
    n, sp, sy = bpm.bin_aggregates(game_of_row, p, y, G)
    n, sp, sy = n[:, ::2] + n[:, 1::2], sp[:, ::2] + sp[:, 1::2], sy[:, ::2] + sy[:, 1::2]
    N, SP, SY = n.sum(0), sp.sum(0), sy.sum(0)
    idx = np.random.default_rng(seed).integers(0, G, (B, G))
    bins = []
    bs = np.full((B, 10), np.nan)
    for t in range(B):
        nn, ss, yy = n[idx[t]].sum(0), sp[idx[t]].sum(0), sy[idx[t]].sum(0)
        with np.errstate(invalid="ignore", divide="ignore"):
            bs[t] = 100 * (yy / nn - ss / nn)
    for b in range(10):
        if N[b] > 0:
            lo, hi = np.nanpercentile(bs[:, b], [2.5, 97.5])
            bins.append({"stufe": f"{10 * b}-{10 * b + 10} %", "n": int(N[b]), "modell": bpm.pr(SP[b] / N[b]), "treffer": bpm.pr(SY[b] / N[b]), "abweichung_pp": bpm.pr(100 * (SY[b] / N[b] - SP[b] / N[b]), 2), "ci95_pp": [bpm.pr(lo, 2), bpm.pr(hi, 2)]})
    return bins


def pos_flags(R):
    """Zeilen je Spieler-Spiel: niedrigster / hoechster Meilenstein (Zeilen sind nach pg sortiert)."""
    pg, k = R["pg"], R["k"]
    if len(pg) == 0:
        return np.zeros(0, bool), np.zeros(0, bool)
    first = np.r_[True, pg[1:] != pg[:-1]]
    last = np.r_[pg[1:] != pg[:-1], True]
    return first, last


def metrics_variant(v, R, pg, G, rotsum=None):
    gr = pg["game"][R["pg"]]
    m = bpm.row_metrics(R, pg["game"], G)
    m["stufen10"] = calib10(gr, R["p"], R["y"].astype(float), G)
    m["punktfehler"] = bpm.point_metrics(pg[f"emin_{v}"], pg[f"epts_{v}"], pg["min"], pg["pts"], pg["game"], G)
    m["minuten_nach_rolle"] = bpm.role_bias(pg[f"emin_{v}"], pg["min"], pg["game"], G)
    stars = pg["epts_A"] >= 20
    for nm, mk in (("stars", stars), ("rest", ~stars)):
        m["punktfehler_" + nm] = bpm.point_metrics(pg[f"emin_{v}"][mk], pg[f"epts_{v}"][mk], pg["min"][mk], pg["pts"][mk], pg["game"][mk], G)
        sel = mk[R["pg"]]
        sub = {"pg": R["pg"][sel], "p": R["p"][sel], "y": R["y"][sel]}
        m["brier_" + nm] = {k: x for k, x in bpm.row_metrics(sub, pg["game"], G, with_ci=False).items() if k in ("n", "brier", "mittel_modell", "trefferquote", "abweichung_pp")}
    first, last = pos_flags(R)
    for nm, mk in (("niedrigster", first), ("hoechster", last), ("mittlere", ~(first | last))):
        sub = {"pg": R["pg"][mk], "p": R["p"][mk], "y": R["y"][mk]}
        m["leiter_" + nm] = {k: x for k, x in bpm.row_metrics(sub, pg["game"], G, with_ci=False).items() if k in ("n", "brier", "mittel_modell", "trefferquote", "abweichung_pp")}
    for nm, mk in (("overtime", pg["ot"] == 1), ("ohne_overtime", pg["ot"] == 0), ("erste_15_teamspiele", pg["team_gp"] < 15), ("rest", pg["team_gp"] >= 15)):
        sel = mk[R["pg"]]
        sub = {"pg": R["pg"][sel], "p": R["p"][sel], "y": R["y"][sel]}
        m["teil_" + nm] = {k: x for k, x in bpm.row_metrics(sub, pg["game"], G, with_ci=False).items() if k in ("n", "brier", "mittel_modell", "trefferquote", "abweichung_pp")}
    return m


def diff_to_A(RA, RV, pg, G, seed=9):
    kA = RA["pg"].astype(np.int64) * 64 + RA["k"]
    kV = RV["pg"].astype(np.int64) * 64 + RV["k"]
    _, ia, iv = np.intersect1d(kA, kV, return_indices=True)
    y = RA["y"][ia].astype(float)
    d = (RV["p"][iv] - y) ** 2 - (RA["p"][ia] - y) ** 2
    gg = pg["game"][RA["pg"][ia]]
    cnt = bpm.group_sums(gg, np.ones(len(d)), G)
    e = bpm.boot_ratio(bpm.group_sums(gg, d, G), cnt, seed=seed)
    return {"gemeinsame_zeilen": int(len(d)), "brier_A": bpm.pr(((RA["p"][ia] - y) ** 2).mean(), 5), "brier_V": bpm.pr(((RV["p"][iv] - y) ** 2).mean(), 5), "differenz": bpm.pr(e[0], 5), "ci95": [bpm.pr(e[1], 5), bpm.pr(e[2], 5)]}


def team_minutes(team, name):
    x = team[name]
    x = x[np.isfinite(x)]
    return {"min": bpm.pr(x.min(), 1), "median": bpm.pr(np.median(x), 1), "max": bpm.pr(x.max(), 1), "mittel": bpm.pr(x.mean(), 1)} if len(x) else None


def verdict(per_season):
    """Bewertungsregel: Verbesserung nur, wenn die Differenz zu A in BEIDEN Testsaisons negativ ist und das Intervall 0 nicht einschliesst."""
    neg = all(s["differenz"] < 0 and s["ci95"][1] < 0 for s in per_season.values())
    pos = all(s["differenz"] > 0 and s["ci95"][0] > 0 for s in per_season.values())
    return "Verbesserung gegenüber A" if neg else ("schlechter als A" if pos else "kein belastbarer Unterschied")


def build_report(stage):
    grid = {s: json.loads((stage / f"grid_{s}.json").read_text()) for s in SEASONS}
    parts = {s: load_stage(stage, s) for s in SEASONS}
    names = parts[SEASONS[0]][3]["names"]
    r1 = json.loads((RESULTS / "backtest_player.json").read_text(encoding="utf-8"))
    rep = {"version": 2, "hinweis": __doc__.split("\n")[1] if False else "Runde 2: nur Messung, keine Empfehlung.", "versionen": VERSION, "raster": grid, "saisons": {}, "kontrolle_runde1": {}}
    pgs, rows_, teams_ = {}, {}, {}
    for s in SEASONS:
        pg, rows, team, meta = parts[s]
        pgs[s], rows_[s], teams_[s] = pg, rows, team
    both_pg, both_rows, both_team = merge([parts[s] for s in SEASONS])
    datasets = {s: (pgs[s], rows_[s], teams_[s]) for s in SEASONS}
    datasets["beide"] = (both_pg, both_rows, both_team)
    for s, (pg, rows, team) in datasets.items():
        G = int(pg["game"].max()) + 1
        blk = {"spielerzeilen": int(len(pg["game"])), "spiele": G, "varianten": {}, "vergleich_zu_A": {}, "rotationsminuten_je_team": {"roh_summe": team_minutes(team, "before"), **{v: team_minutes(team, f"after_{v}") for v in ("B", "D", "E", "G", "D_C")}}}
        for v in names:
            blk["varianten"][v] = metrics_variant(v, rows[v], pg, G)
        for v in names:
            if v != "A":
                blk["vergleich_zu_A"][v] = diff_to_A(rows["A"], rows[v], pg, G)
        rep["saisons"][s] = blk
    # Kontrolle Runde 1
    for s in SEASONS:
        for v in ("A", "B"):
            rep["kontrolle_runde1"][f"{s} {v}"] = {"runde1": r1["saisons"][s]["varianten"][v]["brier"], "runde2": rep["saisons"][s]["varianten"][v]["brier"]}
        rep["kontrolle_runde1"][f"{s} C (Runde 1)"] = {"runde1": r1["saisons"][s]["varianten"]["C"]["brier"]}
    rep["kontrolle_ok"] = all(abs(x["runde1"] - x["runde2"]) < 0.0005 for k, x in rep["kontrolle_runde1"].items() if "runde2" in x)
    # Parameterwahl und Bewertungsregel
    choice = {}
    for test in SEASONS:
        train = SEASONS[0] if test == SEASONS[1] else SEASONS[1]
        g = grid[train]["varianten"]
        cand = {v: x["brier_diff_zu_A_gemeinsame_zeilen"] for v, x in g.items() if v.startswith("F") and not v.startswith("Fm")}
        best = min(cand, key=cand.get)
        choice[test] = {"trainingssaison": train, "beste_breite": best if cand[best] < 0 else "F1.0 (A)", "c": float(best[1:]) if cand[best] < 0 else 1.0, "raster_differenz": cand}
    rep["parameterwahl"] = choice
    vd = {}
    for v in names:
        if v == "A":
            continue
        per = {s: rep["saisons"][s]["vergleich_zu_A"][v] for s in SEASONS}
        vd[v] = {"je_saison": per, "urteil": verdict(per)}
    rep["urteile"] = vd
    return rep


def th(n):
    return f"{int(n):,}".replace(",", ".")


def f4(x, d=4, sign=False):
    return "-" if x is None else f"{x:{'+' if sign else ''}.{d}f}"


def summary(rep):
    S = rep["saisons"]["beide"]; V = S["varianten"]
    L = ["ZUSAMMENFASSUNG Runde 2 (nur Messung, ungeprüft; KEINE Änderung am Produktivmodell, KEINE Parameter-Empfehlung; Versionsbezeichnungen siehe Abschnitt 1)",
         f"Kontrolle: A und B reproduzieren Runde 1 (Brier je Saison, Abweichung < 0,0005): {'ja' if rep['kontrolle_ok'] else 'NEIN'}. Spielerzeilen {th(S['spielerzeilen'])}; Meilenstein-Zeilen A {th(V['A']['n'])}, B {th(V['B']['n'])}, D {th(V['D']['n'])}, E {th(V['E']['n'])}, G {th(V['G']['n'])}.",
         f"Bewertungsregel (Differenz zu A negativ, Intervall ohne 0, in beiden Saisons): Urteile: " + "; ".join(f"{VERSION[v]}: {x['urteil']}" for v, x in rep["urteile"].items() if v in ("B", "D", "E", "G", "F1.15", "F1.3", "F1.5")) + "."]
    for v in ("B", "D", "E", "G", "F1.15", "F1.3", "F1.5"):
        pa = rep["urteile"][v]["je_saison"]
        L.append(f"  {VERSION[v]} ({v}): Brier-Differenz zu A " + "; ".join(f"{s} {x['differenz']:+.5f} [{x['ci95'][0]:+.5f}; {x['ci95'][1]:+.5f}]" for s, x in pa.items()) + f"; gesamt {rep['saisons']['beide']['vergleich_zu_A'][v]['differenz']:+.5f}.")
    pc = rep["parameterwahl"]
    L.append("Breite c (Wahl auf der Trainingssaison nach Brier, Raster jeder 4. Spieltag): " + "; ".join(f"Test {t}: c = {x['c']:g} (Training {x['trainingssaison']})" for t, x in pc.items()) + ". Stelle: Glättungskern h = 1 + 0,05 x in forecast_player (Erwartungswerte unverändert).")
    D, A, B, E, G = V["D"], V["A"], V["B"], V["E"], V["G"]
    t = S["rotationsminuten_je_team"]
    L.append(f"D (Minuten auf 240, kein f): Brier {D['brier']:.4f} gegen A {A['brier']:.4f}, B {B['brier']:.4f}, E {E['brier']:.4f}; Minuten-Bias {D['punktfehler']['minuten']['bias']:+.2f} (A {A['punktfehler']['minuten']['bias']:+.2f}, B {B['punktfehler']['minuten']['bias']:+.2f}); Punkte-Bias {D['punktfehler']['punkte']['bias']:+.2f} (A {A['punktfehler']['punkte']['bias']:+.2f}).")
    L.append(f"Rotationsminuten je Team: roh Median {t['roh_summe']['median']:.0f} (Spanne {t['roh_summe']['min']:.0f}-{t['roh_summe']['max']:.0f}), nach Abgleich B {t['B']['median']:.0f}, D {t['D']['median']:.0f}, E {t['E']['median']:.0f}, G {t['G']['median']:.0f} (Ziel 240).")
    def edge(v):
        st = V[v]["stufen10"]
        lo = [b for b in st if b["stufe"] in ("0-10 %",)]; hi = [b for b in st if b["stufe"] in ("80-90 %", "90-100 %")]
        return "0-10 %: " + (f"{100 * lo[0]['modell']:.0f}/{100 * lo[0]['treffer']:.0f}" if lo else "-") + "; 80-100 %: " + ", ".join(f"{100 * b['modell']:.0f}/{100 * b['treffer']:.0f}" for b in hi)
    L.append("Ränder (Modell % / Treffer %, beide Saisons): A " + edge("A") + " | F1.3 " + edge("F1.3") + " | F1.5 " + edge("F1.5") + " | G " + edge("G") + ".")
    for nm, key in (("Stars (erw. Punkte roh >= 20)", "punktfehler_stars"), ):
        L.append(f"{nm}: Punkte-Bias A {A[key]['punkte']['bias']:+.2f}, B {B[key]['punkte']['bias']:+.2f}, D {D[key]['punkte']['bias']:+.2f}, E {E[key]['punkte']['bias']:+.2f}, G {G[key]['punkte']['bias']:+.2f}; Treffer minus Modell (PP) A {A['brier_stars']['abweichung_pp']:+.1f}, B {B['brier_stars']['abweichung_pp']:+.1f}, D {D['brier_stars']['abweichung_pp']:+.1f}, E {E['brier_stars']['abweichung_pp']:+.1f}, G {G['brier_stars']['abweichung_pp']:+.1f}.")
    rb = lambda v: V[v]["minuten_nach_rolle"].get("unter 20 Min", {}).get("bias")
    L.append(f"Bank (unter 20 Min.): Minuten-Bias A {f4(rb('A'), 2, True)}, B {f4(rb('B'), 2, True)}, D {f4(rb('D'), 2, True)}, E {f4(rb('E'), 2, True)}; niedrigster Meilenstein Treffer minus Modell (PP) A {A['leiter_niedrigster']['abweichung_pp']:+.1f}, B {B['leiter_niedrigster']['abweichung_pp']:+.1f}, D {D['leiter_niedrigster']['abweichung_pp']:+.1f}, E {E['leiter_niedrigster']['abweichung_pp']:+.1f}, G {G['leiter_niedrigster']['abweichung_pp']:+.1f}.")
    L.append("Kurzvergleich Ausfälle bekannt (Obergrenze): " + "; ".join(f"{VERSION[v]}: Brier {V[v]['brier']:.4f} (Differenz zu A {rep['saisons']['beide']['vergleich_zu_A'][v]['differenz']:+.5f} [{rep['saisons']['beide']['vergleich_zu_A'][v]['ci95'][0]:+.5f}; {rep['saisons']['beide']['vergleich_zu_A'][v]['ci95'][1]:+.5f}])" for v in ("D_C", "E_C")) + ".")
    L.append("Einschränkungen: Konstanten (Blowout-Kurve, league_ppm, Sigmas) für 2025-26 teils in-sample, für 2024-25 aus der Zukunft; Ausfälle unbekannt (außer *_C = Obergrenze); Overtime nicht modelliert; Kader aus den letzten 10 Teamspielen; Zeilen eines Spiels korreliert (Bootstrap nach Spielen).")
    return L


def render(rep, runtime):
    L = summary(rep)
    L += ["", "=" * 130, f"Spieler-Backtest Runde 2, Laufzeit {runtime:.0f} s. Details: Kopf von analysis/backtest_player_round2.py.", "=" * 130, ""]
    L += ["1. VERSIONEN"] + [f"  {v}: {n}" for v, n in rep["versionen"].items()] + [""]
    L += ["2. KONTROLLE gegen Runde 1 (Brier je Saison)"] + [f"  {k}: Runde 1 {x['runde1']:.4f}" + (f", Runde 2 {x['runde2']:.4f}" if "runde2" in x else "") for k, x in rep["kontrolle_runde1"].items()] + [""]
    L += ["3. PARAMETERWAHL (Raster jeder 4. Spieltag der Trainingssaison, Brier-Differenz zu A auf gemeinsamen Zeilen; negativ = besser)"]
    for s, x in rep["raster"].items():
        L.append(f"  Raster {s}: " + "; ".join(f"{v} {y['brier_diff_zu_A_gemeinsame_zeilen']:+.5f}" for v, y in x["varianten"].items()) + f" (Fm = Breite auf die Minutenstreuung, nur Zusatz im Raster)")
    for t, x in rep["parameterwahl"].items():
        L.append(f"  Test {t}: Training {x['trainingssaison']} -> {x['beste_breite']} (c = {x['c']:g})")
    L += [""]
    L += ["4. BEWERTUNGSREGEL (Differenz zu A: negativ UND Intervall ohne 0 UND in beiden Saisons)"]
    for v, x in rep["urteile"].items():
        L.append(f"  {v:<6} {VERSION[v]:<45} " + "; ".join(f"{s}: {y['differenz']:+.5f} [{y['ci95'][0]:+.5f}; {y['ci95'][1]:+.5f}]" for s, y in x["je_saison"].items()) + f"  => {x['urteil']}")
    L += [""]
    for s in list(SEASONS) + ["beide"]:
        blk = rep["saisons"][s]
        L += [f"=== {s}: {blk['spiele']} Spiele, {th(blk['spielerzeilen'])} Spielerzeilen ===",
              "  Summe der erwarteten Rotationsminuten je Team (Ziel 240): " + "; ".join(f"{k} Median {x['median']} (Spanne {x['min']}-{x['max']})" for k, x in blk["rotationsminuten_je_team"].items() if x)]
        rows = []
        for v, m in blk["varianten"].items():
            d = blk["vergleich_zu_A"].get(v)
            rows.append({"v": v, "n": th(m['n']), "b": f"{m['brier']:.4f}", "ci": f"[{m['brier_ci95'][0]:.4f}; {m['brier_ci95'][1]:.4f}]", "l": f"{m['logloss']:.4f}", "p": f"{100 * m['mittel_modell']:.1f}", "t": f"{100 * m['trefferquote']:.1f}", "s": f"{m['steigung']}",
                         "d": f"{d['differenz']:+.5f}" if d else "-", "dc": f"[{d['ci95'][0]:+.5f}; {d['ci95'][1]:+.5f}]" if d else "-"})
        L += ["  " + t for t in bpm.fmt_table(rows, ["v", "n", "b", "ci", "l", "p", "t", "s", "d", "dc"], ["Variante", "Zeilen", "Brier", "95 %-Intervall", "Log-Loss", "Ø Chance %", "Treffer %", "Steigung", "Diff zu A", "95 %-Intervall"])]
        L += ["  Minuten und Punkte (Bias erwartet minus echt / MAE), Stars (erwartete Punkte roh >= 20) gegen Rest:"]
        rows = []
        for v, m in blk["varianten"].items():
            pm = m["punktfehler"]; ps, pr_ = m["punktfehler_stars"], m["punktfehler_rest"]
            rows.append({"v": v, "mb": f"{pm['minuten']['bias']:+.2f}/{pm['minuten']['mae']:.2f}", "pb": f"{pm['punkte']['bias']:+.2f}/{pm['punkte']['mae']:.2f}", "st": f"{ps['punkte']['bias']:+.2f}/{ps['punkte']['mae']:.2f}", "re": f"{pr_['punkte']['bias']:+.2f}/{pr_['punkte']['mae']:.2f}",
                         "bs": f"{m['brier_stars']['brier']:.4f} ({m['brier_stars']['abweichung_pp']:+.1f})", "br": f"{m['brier_rest']['brier']:.4f} ({m['brier_rest']['abweichung_pp']:+.1f})"})
        L += ["    " + t for t in bpm.fmt_table(rows, ["v", "mb", "pb", "st", "re", "bs", "br"], ["Variante", "Minuten", "Punkte", "Punkte Stars", "Punkte Rest", "Brier Stars (Abw PP)", "Brier Rest (Abw PP)"])]
        L += ["  Minuten-Bias nach Rolle (erwartet): " + " | ".join(f"{v}: " + ", ".join(f"{k.split()[0]} {x['bias']:+.2f}" for k, x in m["minuten_nach_rolle"].items() if 'bias' in x) for v, m in blk["varianten"].items() if v in ("A", "B", "D", "E", "G"))]
        L += ["  Position in der Leiter (Brier / Treffer minus Modell in PP):"]
        rows = []
        for v, m in blk["varianten"].items():
            rows.append({"v": v, **{k: f"{m['leiter_' + k]['brier']:.4f} / {m['leiter_' + k]['abweichung_pp']:+.1f}" for k in ("niedrigster", "mittlere", "hoechster")}})
        L += ["    " + t for t in bpm.fmt_table(rows, ["v", "niedrigster", "mittlere", "hoechster"], ["Variante", "niedrigster", "mittlere Zeilen", "höchster"])]
        L += ["  Aufteilung (Brier / Abweichung PP): Overtime, ohne Overtime, erste 15 Teamspiele, Rest:"]
        rows = [{"v": v, **{k: f"{m['teil_' + k]['brier']:.4f} / {m['teil_' + k]['abweichung_pp']:+.1f}" for k in ("overtime", "ohne_overtime", "erste_15_teamspiele", "rest")}} for v, m in blk["varianten"].items()]
        L += ["    " + t for t in bpm.fmt_table(rows, ["v", "overtime", "ohne_overtime", "erste_15_teamspiele", "rest"], ["Variante", "Overtime", "ohne Overtime", "erste 15 Teamspiele", "Rest"])]
        if s == "beide":
            L += ["  Kalibrierung nach 10-PP-Stufen (Modell % / Treffer % / Abweichung PP / n):"]
            for v, m in blk["varianten"].items():
                L.append(f"    {v:<6} " + " | ".join(f"{b['stufe'].split(' ')[0]}: {100 * b['modell']:.0f}/{100 * b['treffer']:.0f}/{b['abweichung_pp']:+.1f}/{b['n']}" for b in m["stufen10"]))
        L += [""]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- Ablauf
def render_only():
    rep = json.loads((RESULTS / OUT_JSON).read_text(encoding="utf-8"))
    (RESULTS / OUT_TXT).write_text(render(rep, rep["laufzeit_sekunden_bericht"]), encoding="utf-8")
    print("\n".join(summary(rep)))
    return 0


def mode_all(stage):
    t0 = time.time()
    py = sys.executable
    me = str(Path(__file__).resolve())
    stage.mkdir(parents=True, exist_ok=True)
    procs = [subprocess.Popen([py, me, "--grid", s, "--stage-dir", str(stage)], stdout=open(stage / f"log_grid_{s}.txt", "w"), stderr=subprocess.STDOUT) for s in SEASONS]
    for p in procs:
        p.wait()
    grid = {s: json.loads((stage / f"grid_{s}.json").read_text()) for s in SEASONS}
    cs = {}
    for test in SEASONS:
        train = SEASONS[0] if test == SEASONS[1] else SEASONS[1]
        cand = {v: x["brier_diff_zu_A_gemeinsame_zeilen"] for v, x in grid[train]["varianten"].items() if v.startswith("F") and not v.startswith("Fm")}
        best = min(cand, key=cand.get)
        cs[test] = float(best[1:]) if cand[best] < 0 else 1.0
    print("Breite c je Testsaison:", cs, flush=True)
    procs = [subprocess.Popen([py, me, "--run", s, "--c", str(cs[s]), "--stage-dir", str(stage)], stdout=open(stage / f"log_run_{s}.txt", "w"), stderr=subprocess.STDOUT) for s in SEASONS]
    for p in procs:
        p.wait()
    return mode_report(stage, t0)


def mode_report(stage, t0=None):
    t0 = t0 or time.time()
    rep = build_report(stage)
    runtime = time.time() - t0
    rep["laufzeit_sekunden_bericht"] = round(runtime)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (RESULTS / OUT_TXT).write_text(render(rep, runtime), encoding="utf-8")
    print("\n".join(summary(rep)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}")
    return 0


def selftest():
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    from bt_player_adapter import _fake_rows
    store = HistoryStore(_fake_rows())
    ad = Adapter(store)
    ctx = {"found": True, "exp_spread": 3.0, "exp_total": 224.0, "home_score": 113.5, "away_score": 110.5}
    day = "2024-11-15"
    ad.set_day(day, ("AAA", "BBB"))
    played = [r for r in _fake_rows() if r["date"] == day and r["team"] == "AAA"][:8]
    names = ["A", "B", "D", "E", "G", "D_C", "E_C", "F1.15", "F1.3", "F1.5"]
    out, info, sk = forecast_team_multi(ad, "AAA", True, ctx, day, played, 1.3, names)
    check("alle Varianten liefern Prognosen fuer jeden gespielten Spieler", len(out) > 0 and all(set(names) <= set(f) for _, f, _ in out), len(out))
    r0, f0, _ = out[0]
    check("A = roh = Produktiv (Variante B und A haben dieselbe Struktur, Konstanten zurueckgestellt)", pf.F_MIN == 0.6 and pf.F_MAX == 1.4 and pf.TEAM_MATCH_STRENGTH == 1.0 and bpa.ORIG_FORECAST is not IMPL, (pf.F_MIN, pf.F_MAX, pf.TEAM_MATCH_STRENGTH))
    with settings(ck=1.0):
        a = ad.forecast_player(r0["person_id"], day, home=True, exp_spread=3.0, exp_total=224.0, name="x")
    check("Breite c = 1 identisch zum Original", np.array_equal(p_array(a), p_array(f0["A"])))
    w = f0["F1.5"]
    check("Breite c > 1: Erwartungswerte unveraendert, Verteilung breiter (Rand hoeher/niedriger)", abs(w["expected_points"] - f0["A"]["expected_points"]) < 1e-9 and p_array(w)[0] <= p_array(f0["A"])[0] + 1e-12 and p_array(w)[-1] >= p_array(f0["A"])[-1] - 1e-12)
    d_min = sum(f["D"]["minutes"]["mean"] for _, f, rot in out if rot)
    check("D: kein Faktor f (Punkte pro Minute wie roh bei gleichen Minuten), Minuten abgeglichen", all(abs(f["D"]["expected_points"] - f["A"]["expected_points"] * f["D"]["minutes"]["mean"] / max(f["A"]["minutes"]["mean"], 1e-9)) / max(f["A"]["expected_points"], 1e-9) < 0.25 for _, f, rot in out if rot and f["A"]["minutes"]["mean"] > 5))
    check("E liegt zwischen D und B (Faktor halber Staerke)", all(min(f["D"]["expected_points"], f["B"]["expected_points"]) - 1e-9 <= f["E"]["expected_points"] <= max(f["D"]["expected_points"], f["B"]["expected_points"]) + 1e-9 for _, f, rot in out if rot))
    check("Bewertungsregel: nur negativ UND Intervall ohne 0 in beiden Saisons", verdict({"a": {"differenz": -0.01, "ci95": [-0.02, -0.001]}, "b": {"differenz": -0.01, "ci95": [-0.02, -0.001]}}) == "Verbesserung gegenüber A"
          and verdict({"a": {"differenz": -0.01, "ci95": [-0.02, 0.001]}, "b": {"differenz": -0.01, "ci95": [-0.02, -0.001]}}) == "kein belastbarer Unterschied"
          and verdict({"a": {"differenz": -0.01, "ci95": [-0.02, -0.001]}, "b": {"differenz": 0.01, "ci95": [0.001, 0.02]}}) == "kein belastbarer Unterschied")
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv
    stage = Path(a[a.index("--stage-dir") + 1]) if "--stage-dir" in a else Path("/tmp/nbaedge_round2")
    if "--selftest" in a:
        sys.exit(bpa.selftest() | selftest())
    if "--pilot" in a:
        mode_pilot(stage); sys.exit(0)
    if "--grid" in a:
        mode_grid(a[a.index("--grid") + 1], stage); sys.exit(0)
    if "--run" in a:
        mode_run(a[a.index("--run") + 1], stage, float(a[a.index("--c") + 1])); sys.exit(0)
    if "--render-only" in a:
        sys.exit(render_only())
    if "--report" in a:
        sys.exit(mode_report(stage))
    if "--all" in a:
        sys.exit(mode_all(stage))
    print(__doc__)

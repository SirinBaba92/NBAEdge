"""
Team-Backtest ueber mehrere Saisons (Stabilitaets-Check der Befunde aus 2025-26). NUR LESEND: liest data/cache (games_2015 bis games_2025), schreibt nur
analysis/results/backtest_team_multiseason.json und analysis/results/backtest_team_multiseason.txt. Keine API-Calls, Produktivcode und bestehende Dateien bleiben unveraendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/backtest_team_multiseason.py            Selbsttest:  venv/bin/python analysis/backtest_team_multiseason.py --selftest

Wiederverwendet (importiert, nicht kopiert) aus analysis/backtest_team_markets.py: kausaler Replay (replica_tunable, Produktivparameter), Spalten-Aufbereitung (prepare), Berichte je Markt
(market_report, win_report, light_report, win_light), Bootstrap, Stufen- und Abdeckungslogik. REINES MODELL ohne Markt-Mischung (die App mischt den Markt dazu). Saison-Zuordnung: das Feld
"season" der Spieldaten (Startjahr, 2017 = 2017-18); Regular Season = postseason false, Playoffs = postseason true (Zusatz). Bias immer Modell minus Ergebnis.
Overtime wird ueber die OT-Punkte (home_ot1) erkannt, nicht ueber das Feld period (vor 2019 unzuverlaessig; in 2025-26 liefern beide dieselben 56 Spiele).
HINWEIS: Sigmas (sigma_check, Saisons 2017-2025) und Teile der ELO-Parameter (Faktor 50, Heimvorteil, MOV-Wahl; tuning_*-Analysen) wurden auf diesen Saisons abgestimmt. Die aelteren Saisons
sind deshalb KEIN vollstaendig unabhaengiger Test (der Replay selbst ist kausal; die Parameterwahl nicht). Reine Beschreibung, keine Empfehlungen zu Produktivparametern.
"""
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backtest_team_markets as btm  # noqa: E402
from backtest_team_markets import (MARKETS, KS, PRODUCTION, load_games, lp, rt, pr, fp, subset, point_errors, light_report, win_light, win_report, market_report,  # noqa: E402
                                   boot_mean_ci, covered_text, verdict_slope, slope_fit)
from config.settings import ELO_TO_SPREAD_FACTOR  # noqa: E402

RESULTS = HERE / "results"
OUT_JSON, OUT_TXT = "backtest_team_multiseason.json", "backtest_team_multiseason.txt"
FIRST_SEASON = 2017
SHORT_SEASONS = {2019: "verkürzt (Corona-Unterbrechung, Ende in der Bubble)", 2020: "verkürzt (72 Spiele je Team)"}
EXPECTED_RS = 1230
KEYS = {"spread": ("mu_s", "margin"), "total": ("mu_t", "total"), "tt_home": ("mu_h", "pts_h"), "tt_away": ("mu_a", "pts_a")}


def label(s):
    return f"{s}-{(s + 1) % 100:02d}"


def concat(ds):
    out = {}
    for k in ds[0]:
        v = [d[k] for d in ds]
        out[k] = np.concatenate([np.asarray(x) for x in v]) if isinstance(v[0], np.ndarray) else sum((list(x) for x in v), [])
    return out


def ot_flags(games, idx):
    """Overtime je Spiel: Punkte der 1. Verlaengerung vorhanden (home_ot1) oder period > 4. Das Feld period allein ist vor 2019 nicht verlaesslich (0 Treffer 2015-2017, 22 von 67 in 2018)."""
    return np.array([int(games[i].get("home_ot1") is not None or (games[i].get("period") or 4) > 4) for i in idx])


def gaps(games, season):
    """Kontrolle auf Luecken: Spiele je Team (min/max), laengste Pause zwischen zwei Spieltagen der Regular Season in Tagen."""
    rs = [g for g in games if g["season"] == season and not g.get("postseason")]
    per = defaultdict(int)
    for g in rs:
        per[g["home_team"]["full_name"]] += 1
        per[g["visitor_team"]["full_name"]] += 1
    ds = sorted({g["date"][:10] for g in rs})
    ints = [date.fromisoformat(ds[i + 1]) - date.fromisoformat(ds[i]) for i in range(len(ds) - 1)]
    longest = max((x.days for x in ints), default=0)
    return {"spiele": len(rs), "teams": len(per), "spiele_je_team_min": min(per.values()) if per else None, "spiele_je_team_max": max(per.values()) if per else None,
            "erster_tag": ds[0] if ds else None, "letzter_tag": ds[-1] if ds else None, "laengste_pause_tage": longest, "differenz_zu_1230": len(rs) - EXPECTED_RS}


def season_block(d):
    """Alle Kennzahlen einer Saison (Regular Season) plus Playoff-Zusatz. d = prepare()-Arrays der Saison (RS und Playoffs)."""
    rs = d["post"] == 0
    r = subset(d, rs)
    n = int(rs.sum())
    sieg, p, y = win_report(r["mu_s"], r["margin"])
    blk = {"n": n, "sieg": {k: sieg[k] for k in ("mittel_p_heim", "heimsieg_quote", "brier", "logloss", "steigung", "trefferquote_favorit")}, "favorit_stufen": sieg["favorit_stufen"]}
    for key, (mu, x) in KEYS.items():
        lr = light_report(r[mu], r[x], MARKETS[key][1])
        lr["abweichung_hauptlinie_pp"] = pr(100 * (lr["hauptlinie_trefferquote"] - lr["hauptlinie_mittel_modell"]), 2) if lr.get("n", 0) >= 5 else None
        blk[key] = lr
    ot = r["ot"].astype(bool)
    mu_t, tot = r["mu_t"], r["total"]
    blk["overtime"] = {"anteil": pr(ot.mean(), 4), "n_ot": int(ot.sum()), "total_mit_ot": pr(tot[ot].mean(), 2) if ot.any() else None, "total_ohne_ot": pr(tot[~ot].mean(), 2),
                       "total_bias_gesamt": pr((mu_t - tot).mean(), 2), "total_bias_ohne_ot": pr((mu_t - tot)[~ot].mean(), 2), "total_bias_nur_ot": pr((mu_t - tot)[ot].mean(), 2) if ot.any() else None}
    f15 = (r["gp_h"] < 15) & (r["gp_a"] < 15)
    sf, sr = win_light(r["mu_s"][f15], r["margin"][f15]), win_light(r["mu_s"][~f15], r["margin"][~f15])
    blk["saisonstart"] = {"n_erste15": int(f15.sum()), "total_bias_erste15": pr((mu_t - tot)[f15].mean(), 2) if f15.any() else None, "total_bias_rest": pr((mu_t - tot)[~f15].mean(), 2),
                          "sieg_steigung_erste15": sf.get("steigung"), "sieg_steigung_rest": sr.get("steigung")}
    h1 = np.arange(n) < n // 2
    a, b = win_light(r["mu_s"][h1], r["margin"][h1]), win_light(r["mu_s"][~h1], r["margin"][~h1])
    blk["haelften"] = {"sieg_steigung_1": a.get("steigung"), "sieg_steigung_2": b.get("steigung"), "favorit_trefferquote_1": a.get("trefferquote_favorit"), "favorit_trefferquote_2": b.get("trefferquote_favorit")}
    po = d["post"] == 1
    pd_ = subset(d, po)
    blk["playoffs"] = {"n": int(po.sum()), "total_bias": pr((pd_["mu_t"] - pd_["total"]).mean(), 2) if po.any() else None, "spread_bias": pr((pd_["mu_s"] - pd_["margin"]).mean(), 2) if po.any() else None}
    blk["heimvorteil"] = {"modell": pr(r["mu_s"].mean(), 2), "tatsaechlich": pr(r["margin"].mean(), 2), "differenz": pr(r["mu_s"].mean() - r["margin"].mean(), 2)}
    return blk


def spread_of(per, getter):
    """min / max / Mittel einer Kennzahl ueber die Saisons (None-Werte werden uebergangen): {'min': (Wert, Saison), 'max': (...), 'mittel'}."""
    vals = [(getter(b), s) for s, b in per.items() if getter(b) is not None]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    return {"min": [lo[0], lo[1]], "max": [hi[0], hi[1]], "mittel": pr(float(np.mean([v for v, _ in vals])), 3)}


def pooled_report(dall):
    r = subset(dall, dall["post"] == 0)
    out = {"n": int(len(r["mu_s"]))}
    sieg, p, y = win_report(r["mu_s"], r["margin"])
    hitf = np.where(p >= .5, y, 1 - y)
    ci = lambda v: [pr(x, 4) for x in boot_mean_ci(v, seed=11)[1:]]
    sieg["brier_ci95"], sieg["logloss_ci95"] = ci((p - y) ** 2), ci(btm.ll(p, y))
    sieg["favorit_trefferquote_ci95"] = ci(hitf)
    out["sieg"] = sieg
    for key, (mu, x) in KEYS.items():
        out[key] = {"name": MARKETS[key][0], "sigma": MARKETS[key][1], **market_report(r[mu], r[x], MARKETS[key][1])}
    po = subset(dall, dall["post"] == 1)
    out["playoffs"] = {"n": int(len(po["mu_s"])), "fehler": {k: point_errors(po[KEYS[k][0]], po[KEYS[k][1]]) for k in KEYS}} if len(po["mu_s"]) >= 5 else {"n": int(len(po["mu_s"]))}
    return out


def build(games, rows, seasons):
    per, ds, ctl = {}, [], {}
    for s in seasons:
        btm.SEASON = s
        d = btm.prepare(games, rows)
        d["ot"] = ot_flags(games, d["idx"])                                  # ersetzt die period-Erkennung der 2025-26-Auswertung (dort identisch: 56 OT-Spiele)
        ds.append(d)
        per[s] = season_block(d)
        ctl[s] = gaps(games, s)
    pooled = pooled_report(concat(ds))
    return per, pooled, ctl


def stability(per):
    """Kennzahlen ueber die Saisons: min/max/Mittel und Zaehlungen fuer die Befunde aus 2025-26."""
    S = len(per)
    g = lambda f: spread_of(per, f)
    st = {"saisons": S,
          "sieg_brier": g(lambda b: b["sieg"]["brier"]), "sieg_steigung": g(lambda b: b["sieg"]["steigung"]), "favorit_trefferquote": g(lambda b: b["sieg"]["trefferquote_favorit"]),
          "spread_mae": g(lambda b: b["spread"]["mae"]), "total_mae": g(lambda b: b["total"]["mae"]), "tt_home_mae": g(lambda b: b["tt_home"]["mae"]), "tt_away_mae": g(lambda b: b["tt_away"]["mae"]),
          "spread_bias": g(lambda b: b["spread"]["bias"]), "total_bias": g(lambda b: b["total"]["bias"]), "total_bias_ohne_ot": g(lambda b: b["overtime"]["total_bias_ohne_ot"]),
          "ot_anteil": g(lambda b: b["overtime"]["anteil"]), "total_erste15": g(lambda b: b["saisonstart"]["total_bias_erste15"]), "total_rest": g(lambda b: b["saisonstart"]["total_bias_rest"]),
          "sieg_steigung_erste15": g(lambda b: b["saisonstart"]["sieg_steigung_erste15"]), "sieg_steigung_rest": g(lambda b: b["saisonstart"]["sieg_steigung_rest"]),
          "playoff_total_bias": g(lambda b: b["playoffs"]["total_bias"]), "playoff_spread_bias": g(lambda b: b["playoffs"]["spread_bias"]), "heimvorteil_differenz": g(lambda b: b["heimvorteil"]["differenz"]),
          "heim_p_gegen_quote": g(lambda b: pr(b["sieg"]["mittel_p_heim"] - b["sieg"]["heimsieg_quote"], 3))}
    st["zaehlung"] = {
        "sieg_steigung_ueber_1": sum(1 for b in per.values() if (b["sieg"]["steigung"] or 0) > 1.0),
        "favorit_70_80_treffer_ueber_modell": sum(1 for b in per.values() for f in b["favorit_stufen"] if f["stufe"] == "70-80 %" and f["abweichung_pp"] > 0),
        "favorit_70_80_vorhanden": sum(1 for b in per.values() for f in b["favorit_stufen"] if f["stufe"] == "70-80 %"),
        "total_bias_negativ": sum(1 for b in per.values() if b["total"]["bias"] < 0),
        "ot_zieht_total_bias_nach_unten": sum(1 for b in per.values() if b["overtime"]["total_bias_ohne_ot"] is not None and b["overtime"]["total_bias_ohne_ot"] > b["overtime"]["total_bias_gesamt"]),
        "total_bias_ohne_ot_nahe_0": sum(1 for b in per.values() if abs(b["overtime"]["total_bias_ohne_ot"]) < abs(b["overtime"]["total_bias_gesamt"])),
        "erste15_total_negativ": sum(1 for b in per.values() if (b["saisonstart"]["total_bias_erste15"] or 0) < 0),
        "erste15_total_unter_minus2": sum(1 for b in per.values() if (b["saisonstart"]["total_bias_erste15"] or 0) <= -2.0),
        "erste15_steigung_ueber_rest": sum(1 for b in per.values() if (b["saisonstart"]["sieg_steigung_erste15"] or 0) > (b["saisonstart"]["sieg_steigung_rest"] or 0)),
        "steigung_2_haelfte_groesser": sum(1 for b in per.values() if (b["haelften"]["sieg_steigung_2"] or 0) > (b["haelften"]["sieg_steigung_1"] or 0)),
        "playoff_total_positiv": sum(1 for b in per.values() if (b["playoffs"]["total_bias"] or 0) > 0),
        "playoff_spread_positiv": sum(1 for b in per.values() if (b["playoffs"]["spread_bias"] or 0) > 0),
        "heimvorteil_modell_hoeher": sum(1 for b in per.values() if b["heimvorteil"]["differenz"] > 0)}
    return st


# ----------------------------------------------------------------------------------------------- Text
def summary_lines(per, pooled, st, ctl):
    S, z = st["saisons"], st["zaehlung"]
    names = [label(s) for s in per]
    rng = lambda k, d=2, sign=False: (lambda v: f"{v['min'][0]:{'+' if sign else ''}.{d}f} ({label(v['min'][1])}) bis {v['max'][0]:{'+' if sign else ''}.{d}f} ({label(v['max'][1])}), Ø {v['mittel']:{'+' if sign else ''}.{d}f}")(st[k])
    tot = sum(b["n"] for b in per.values())
    short = ", ".join(f"{label(s)} n = {ctl[s]['spiele']}" for s in per if s in SHORT_SEASONS)
    worst = max(per, key=lambda s: abs(per[s]["sieg"]["mittel_p_heim"] - per[s]["sieg"]["heimsieg_quote"]))
    ps = pooled["sieg"]
    L = [f"ZUSAMMENFASSUNG: {S} Saisons ({names[0]} bis {names[-1]}, Zuordnung nach dem Feld 'season' der Daten), Regular Season {tot} Spiele; REINES MODELL ohne Markt-Mischung (die App mischt den Markt dazu). Bias = Modell minus Ergebnis.",
         "ACHTUNG: Sigmas (sigma_check 2017-2025) und Teile der ELO-Parameter (Faktor 50, Heimvorteil, MOV-Wahl) wurden auf diesen Saisons abgestimmt: die älteren Saisons sind kein vollständig unabhängiger Test.",
         f"Kontrollen: Spiele je Saison {min(c['spiele'] for c in ctl.values())} bis {max(c['spiele'] for c in ctl.values())} (Standard 1230; abweichend: {short or 'keine verkürzten Saisons'}); Heim-p gegen Heimsiegquote höchstens "
         f"{abs(per[worst]['sieg']['mittel_p_heim'] - per[worst]['sieg']['heimsieg_quote']):.3f} Unterschied ({label(worst)}).",
         f"Favoriten zu vorsichtig (Sieg-Steigung über 1): in {z['sieg_steigung_ueber_1']} von {S} Saisons; Steigung {rng('sieg_steigung')}; gesamt {fp(ps['steigung'], 2)}; Favorit gewinnt gesamt {100 * ps['trefferquote_favorit']:.1f} % "
         f"[{100 * ps['favorit_trefferquote_ci95'][0]:.1f}; {100 * ps['favorit_trefferquote_ci95'][1]:.1f}].",
         f"  Stufe 70-80 %: Treffer über Modell in {z['favorit_70_80_treffer_ueber_modell']} von {z['favorit_70_80_vorhanden']} Saisons (2025-26: 82 % gegen 75 %).",
         f"Overtime und Total-Unterschätzung: Total-Bias negativ (Modell zu niedrig) in {z['total_bias_negativ']} von {S} Saisons ({rng('total_bias', 2, True)}); die OT-Spiele ziehen den Bias nach unten (Bias ohne OT höher als gesamt) "
         f"in {z['ot_zieht_total_bias_nach_unten']} von {S} Saisons; ohne OT-Spiele {rng('total_bias_ohne_ot', 2, True)}; OT-Anteil {rng('ot_anteil', 3)}.",
         f"Saisonstart Total (erste 15 Spiele je Team): Bias negativ in {z['erste15_total_negativ']} von {S} Saisons, mindestens -2 in {z['erste15_total_unter_minus2']} ({rng('total_erste15', 2, True)}; Rest Ø {st['total_rest']['mittel']:+.2f}); "
         f"Sieg-Steigung Start gegen Rest Ø {st['sieg_steigung_erste15']['mittel']:.2f} / {st['sieg_steigung_rest']['mittel']:.2f} (Start höher in {z['erste15_steigung_ueber_rest']} Saisons).",
         f"Erste gegen zweite Hälfte: Sieg-Steigung in der zweiten Hälfte größer in {z['steigung_2_haelfte_groesser']} von {S} Saisons (2025-26: 1,54 gegen 0,91).",
         f"Playoffs: Total-Bias positiv (Modell zu hoch) in {z['playoff_total_positiv']} von {S} Saisons ({rng('playoff_total_bias', 1, True)}); Spread-Bias positiv in {z['playoff_spread_positiv']} ({rng('playoff_spread_bias', 1, True)}).",
         f"Heimvorteil: Modell höher als tatsächlich in {z['heimvorteil_modell_hoeher']} von {S} Saisons, Differenz {rng('heimvorteil_differenz', 2, True)}.",
         f"Schwankung zwischen Saisons: Brier {rng('sieg_brier', 3)}; Spread-MAE {rng('spread_mae')}; Total-MAE {rng('total_mae')}; Team-Total-MAE Heim {rng('tt_home_mae')}, Gast {rng('tt_away_mae')}."]
    for key in ("spread", "total", "tt_home", "tt_away"):
        m = pooled[key]
        f = m["fehler"]
        L.append(f"Alle Saisons {m['name']}: Bias {f['bias']:+.2f} [{f['bias_ci95'][0]:+.2f}; {f['bias_ci95'][1]:+.2f}], MAE {f['mae']:.2f}; {verdict_slope(m)}; Schwellen {covered_text(m['abdeckung_schwellen'])}.")
    L.append(f"Alle Saisons Sieg: Brier {ps['brier']:.4f} [{ps['brier_ci95'][0]:.4f}; {ps['brier_ci95'][1]:.4f}], Steigung {fp(ps['steigung'], 2)}; Schwellen {covered_text(ps['abdeckung_schwellen'])}. Nur Beschreibung, keine Empfehlungen.")
    return L


def season_table(per, cols):
    head = ["Saison", "n"] + [c[0] for c in cols]
    rows = [[label(s), str(b["n"])] + [c[1](b) for c in cols] for s, b in per.items()]
    w = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(head)]
    ln = lambda v: "  ".join(x.rjust(wi) for x, wi in zip(v, w))
    return [ln(head), ln(["-" * wi for wi in w])] + [ln(r) for r in rows]


def f2(x, d=2, sign=False):
    return "-" if x is None else f"{x:{'+' if sign else ''}.{d}f}"


def render(per, pooled, st, ctl, runtime):
    L = summary_lines(per, pooled, st, ctl)
    L += ["", "=" * 120, f"Backtest Team-Märkte über Saisons (Walk-forward, kausaler Replay ab 2015, Produktivparameter). Laufzeit {runtime:.1f} s.", "=" * 120, ""]
    L += ["KONTROLLEN: Spiele je Saison (Regular Season)", "  Saison  Spiele  Teams  je Team min-max  Zeitraum                  längste Pause  Diff. zu 1230  Hinweis"]
    for s, c in ctl.items():
        L.append(f"  {label(s)}  {c['spiele']:>6}  {c['teams']:>5}  {c['spiele_je_team_min']:>6}-{c['spiele_je_team_max']:<6}  {c['erster_tag']} bis {c['letzter_tag']}  {c['laengste_pause_tage']:>9} T  {c['differenz_zu_1230']:>+13}  {SHORT_SEASONS.get(s, '')}")
    L += ["  Overtime-Erkennung: OT-Punkte (home_ot1) oder period > 4 (period allein ist vor 2019 unzuverlässig: 2015-2017 keine, 2018 nur 22 von 67 OT-Spielen).",
          "  Abweichungen von 1230 ohne Hinweis (z. B. +6/+7 ab 2022-23) kommen vermutlich von Play-In- bzw. NBA-Cup-Spielen, die in den Daten als Regular Season (postseason = false) stehen; nicht einzeln geprüft.", ""]
    L += ["1. SIEG je Saison", *season_table(per, [("Heim-p Ø", lambda b: f2(b["sieg"]["mittel_p_heim"], 3)), ("Heimsiege", lambda b: f2(b["sieg"]["heimsieg_quote"], 3)), ("Brier", lambda b: f2(b["sieg"]["brier"], 4)),
                                              ("LogLoss", lambda b: f2(b["sieg"]["logloss"], 3)), ("Steigung", lambda b: f2(b["sieg"]["steigung"], 2)), ("Favorit %", lambda b: f2(100 * b["sieg"]["trefferquote_favorit"], 1))]), ""]
    L += ["   Favorit-Stufen je Saison (Modell % / Treffer % / n)", "  Saison   " + "".join(f"{s:>22}" for s in ("50-60 %", "60-70 %", "70-80 %", "80+ %"))]
    for s, b in per.items():
        cells = {f["stufe"]: f"{100 * f['mittel_modell']:.0f}/{100 * f['trefferquote']:.0f}/{f['n']}" for f in b["favorit_stufen"]}
        L.append(f"  {label(s)}  " + "".join(f"{cells.get(k, '-'):>22}" for k in ("50-60 %", "60-70 %", "70-80 %", "80+ %")))
    L.append("")
    for key in ("spread", "total", "tt_home", "tt_away"):
        L += [f"2. {MARKETS[key][0].upper()} je Saison (Sigma {MARKETS[key][1]}; Abw. Hauptlinie = Trefferquote minus Modell in PP)",
              *season_table(per, [("Bias", lambda b, k=key: f2(b[k]["bias"], 2, True)), ("MAE", lambda b, k=key: f2(b[k]["mae"], 2)), ("Steigung", lambda b, k=key: f2(b[k]["steigung"], 2)),
                                  ("Abw. PP", lambda b, k=key: f2(b[k]["abweichung_hauptlinie_pp"], 1, True))]), ""]
    L += ["3. OVERTIME je Saison", *season_table(per, [("OT-Anteil", lambda b: f2(100 * b["overtime"]["anteil"], 1) + " %"), ("Total mit OT", lambda b: f2(b["overtime"]["total_mit_ot"], 1)),
                                                       ("ohne OT", lambda b: f2(b["overtime"]["total_ohne_ot"], 1)), ("Bias gesamt", lambda b: f2(b["overtime"]["total_bias_gesamt"], 2, True)),
                                                       ("Bias ohne OT", lambda b: f2(b["overtime"]["total_bias_ohne_ot"], 2, True)), ("Bias nur OT", lambda b: f2(b["overtime"]["total_bias_nur_ot"], 1, True))]), ""]
    L += ["4. SAISONSTART (erste 15 Spiele je Team beide Teams) gegen Rest", *season_table(per, [("n Start", lambda b: str(b["saisonstart"]["n_erste15"])), ("Total-Bias Start", lambda b: f2(b["saisonstart"]["total_bias_erste15"], 2, True)),
                                                                                              ("Total-Bias Rest", lambda b: f2(b["saisonstart"]["total_bias_rest"], 2, True)),
                                                                                              ("Sieg-Steigung Start", lambda b: f2(b["saisonstart"]["sieg_steigung_erste15"], 2)), ("Sieg-Steigung Rest", lambda b: f2(b["saisonstart"]["sieg_steigung_rest"], 2))]), ""]
    L += ["5. ERSTE gegen ZWEITE SAISONHÄLFTE", *season_table(per, [("Steigung 1. H.", lambda b: f2(b["haelften"]["sieg_steigung_1"], 2)), ("Steigung 2. H.", lambda b: f2(b["haelften"]["sieg_steigung_2"], 2)),
                                                                   ("Favorit % 1. H.", lambda b: f2(100 * b["haelften"]["favorit_trefferquote_1"], 1)), ("Favorit % 2. H.", lambda b: f2(100 * b["haelften"]["favorit_trefferquote_2"], 1))]), ""]
    L += ["6. PLAYOFFS (Zusatz, Bias = Modell minus Ergebnis)", *season_table({s: {**b, "n": b["playoffs"]["n"]} for s, b in per.items()}, [("Total-Bias", lambda b: f2(b["playoffs"]["total_bias"], 1, True)), ("Spread-Bias", lambda b: f2(b["playoffs"]["spread_bias"], 1, True))]), ""]
    L += ["7. HEIMVORTEIL (Ø Spread des Modells gegen Ø tatsächliche Marge, Heim minus Gast)", *season_table(per, [("Modell", lambda b: f2(b["heimvorteil"]["modell"], 2, True)), ("tatsächlich", lambda b: f2(b["heimvorteil"]["tatsaechlich"], 2, True)),
                                                                                                                  ("Differenz", lambda b: f2(b["heimvorteil"]["differenz"], 2, True))]), ""]
    L += ["SCHWANKUNG ÜBER DIE SAISONS (min / max / Mittel)"]
    for k, v in st.items():
        if isinstance(v, dict) and "min" in v:
            L.append(f"  {k:<26} min {v['min'][0]:>8} ({label(v['min'][1])})   max {v['max'][0]:>8} ({label(v['max'][1])})   Ø {v['mittel']}")
    L += ["", "8. ALLE SAISONS ZUSAMMEN (Regular Season, Bootstrap nach Spielen; Zeilen verschiedener Linien eines Spiels sind nicht unabhängig)"]
    ps = pooled["sieg"]
    L += [f"  Sieg n {ps['n']}: Brier {ps['brier']:.4f} [{ps['brier_ci95'][0]:.4f}; {ps['brier_ci95'][1]:.4f}], Log-Loss {ps['logloss']:.3f} [{ps['logloss_ci95'][0]:.3f}; {ps['logloss_ci95'][1]:.3f}], Steigung {fp(ps['steigung'], 2)}, "
          f"Favorit gewinnt {100 * ps['trefferquote_favorit']:.1f} % [{100 * ps['favorit_trefferquote_ci95'][0]:.1f}; {100 * ps['favorit_trefferquote_ci95'][1]:.1f}]"]
    tab = lambda rows: ["    " + t for t in btm.table(rows, ["stufe", "n", "mittel_modell", "trefferquote", "abweichung_pp"], ["Stufe", "n", "Modell", "Treffer", "Abw. PP"])]
    L += ["  Sieg: vorhergesagte Seite nach 5er-Stufen:", *tab(ps["wahrscheinlichkeitsstufen_vorhergesagte_seite"]), "  Sieg: Favorit-Stufen:", *tab(ps["favorit_stufen"]), f"  Schwellen: {covered_text(ps['abdeckung_schwellen'])}", ""]
    for key in ("spread", "total", "tt_home", "tt_away"):
        m = pooled[key]
        f, g = m["fehler"], m["gesamt_ueber_linien"]
        L += [f"  {m['name']}: n {f['n']}; Bias {f['bias']:+.2f} [{f['bias_ci95'][0]:+.2f}; {f['bias_ci95'][1]:+.2f}]; MAE {f['mae']:.2f} [{f['mae_ci95'][0]:.2f}; {f['mae_ci95'][1]:.2f}]; Brier {g['brier']:.4f}; "
              f"Steigung {fp(g['steigung'], 2)} [{fp(g['steigung_ci95'][0], 2) if g['steigung_ci95'] else '-'}; {fp(g['steigung_ci95'][1], 2) if g['steigung_ci95'] else '-'}]",
              "    vorhergesagte Seite nach 5er-Stufen (alle Linien):", *["  " + t for t in tab(m["wahrscheinlichkeitsstufen_vorhergesagte_seite"])],
              f"    Schwellen (mittlere Abweichung < {btm.MAD_MAX_PP:g} PP, keine Stufe mit >= {btm.MIN_ROWS} Zeilen über {btm.DEV_MAX_PP:g} PP daneben): {covered_text(m['abdeckung_schwellen'])}", ""]
    po = pooled["playoffs"]
    if po.get("fehler"):
        L += [f"  Playoffs alle Saisons (n {po['n']}): " + "; ".join(f"{k} Bias {v['bias']:+.2f} [{v['bias_ci95'][0]:+.2f}; {v['bias_ci95'][1]:+.2f}]" for k, v in po["fehler"].items())]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- Hauptprogramm, Selbsttest
def run_all():
    t0 = time.time()
    games = load_games(2015, 2025)
    rows, _, _, _ = rt.run(games, **PRODUCTION)
    seasons = sorted({int(g["season"]) for g in games if int(g["season"]) >= FIRST_SEASON})
    btm.B_SLOPE = 60                                                       # gepoolt: viele Zeilen, darum weniger Ziehungen fuer die Steigung
    per, pooled, ctl = build(games, rows, seasons)
    st = stability(per)
    rep = {"version": 1, "hinweis": "REINES MODELL ohne Markt-Mischung; Sigmas und Teile der ELO-Parameter wurden auf diesen Saisons abgestimmt (aeltere Saisons nicht vollstaendig unabhaengig).",
           "saison_zuordnung": "Feld 'season' der Spieldaten (Startjahr; 2017 = 2017-18)", "saisons": {label(s): per[s] for s in per}, "kontrollen_je_saison": {label(s): ctl[s] for s in ctl}, "stabilitaet": st, "alle_saisons": pooled}
    runtime = time.time() - t0
    rep["laufzeit_sekunden"] = round(runtime, 1)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / OUT_JSON).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    text = render(per, pooled, st, ctl, runtime)
    (RESULTS / OUT_TXT).write_text(text, encoding="utf-8")
    return per, pooled, st, ctl, runtime


def selftest():
    btm.B_ERR, btm.B_STAGE, btm.B_SLOPE = 200, 100, 20
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
    rng = np.random.default_rng(3)
    teams = [f"Team {i}" for i in range(8)]
    games, gid = [], 0
    for season in (2016, 2017, 2018):                                       # 2016 zaehlt nur fuer das Einlaufen des Replays
        for day in range(1, 61):
            for _ in range(3):
                h, a = rng.choice(8, 2, replace=False)
                gid += 1
                games.append({"id": gid, "date": f"{season}-{10 + day // 31:02d}-{1 + day % 28:02d}", "season": season, "postseason": day > 55, "status": "Final", "home_team": {"full_name": teams[h]},
                              "visitor_team": {"full_name": teams[a]}, "home_team_score": int(rng.normal(113, 11)), "visitor_team_score": int(rng.normal(110, 11)), "period": 5 if rng.random() < 0.06 else 4})
    games.sort(key=lambda g: (g["date"], g["id"]))
    rows, _, _, _ = rt.run(games, **PRODUCTION)
    per, pooled, ctl = build(games, rows, [2017, 2018])
    st = stability(per)
    check("zwei Saisons ausgewertet, Kennzahlen vorhanden", list(per) == [2017, 2018] and all(k in per[2017] for k in ("sieg", "spread", "total", "tt_home", "tt_away", "overtime", "saisonstart", "haelften", "playoffs", "heimvorteil")), list(per[2017]))
    check("Spiele je Saison = Regular-Season-Spiele der Saison", all(per[s]["n"] == ctl[s]["spiele"] for s in per) and per[2017]["n"] == sum(1 for g in games if g["season"] == 2017 and not g["postseason"]), [per[s]["n"] for s in per])
    check("Playoffs getrennt (n > 0), nicht in der Regular-Season-Auswertung", per[2017]["playoffs"]["n"] == sum(1 for g in games if g["season"] == 2017 and g["postseason"]) > 0)
    check("gepoolt = Summe der Saisons", pooled["n"] == sum(per[s]["n"] for s in per))
    check("Overtime-Anteil und Bias-Aufteilung konsistent", all(0 <= per[s]["overtime"]["anteil"] <= 1 for s in per) and per[2017]["overtime"]["total_bias_ohne_ot"] is not None)
    check("Schwankung: min <= Mittel <= max und Zaehlungen <= Saisons", all(v["min"][0] <= v["mittel"] <= v["max"][0] for v in st.values() if isinstance(v, dict) and "min" in v and v is not None) and all(0 <= c <= st["saisons"] for c in st["zaehlung"].values() if c is not None))
    check("Replay kausal: spaeteres Ergebnis aendern veraendert keine fruehere Prognose", (lambda g2: np.allclose(rows["diff"][:-1], rt.run(g2, **PRODUCTION)[0]["diff"][:-1]))([*[dict(g) for g in games[:-1]], {**games[-1], "home_team_score": games[-1]["home_team_score"] + 60}]))
    text = render(per, pooled, st, ctl, 0.0)
    check("Textbericht: Zusammenfassung <= 20 Zeilen mit Hinweis auf nicht unabhaengige Saisons, alle Abschnitte", len(summary_lines(per, pooled, st, ctl)) <= 20 and "kein vollständig unabhängiger Test" in text and all(f"{i}. " in text for i in range(1, 8)) and "8. ALLE SAISONS" in text, len(summary_lines(per, pooled, st, ctl)))
    ot = ot_flags([{"home_ot1": 10, "period": 4}, {"home_ot1": None, "period": 6}, {"home_ot1": None, "period": 0}, {"home_ot1": None}], [0, 1, 2, 3])
    check("OT-Erkennung: ot1 oder period > 4; period 0/fehlend zaehlt nicht als OT", list(ot) == [1, 1, 0, 0], list(ot))
    c = gaps([{"season": 2017, "postseason": False, "date": "2017-10-01", "home_team": {"full_name": "A"}, "visitor_team": {"full_name": "B"}},
              {"season": 2017, "postseason": False, "date": "2017-10-20", "home_team": {"full_name": "A"}, "visitor_team": {"full_name": "B"}}], 2017)
    check("Luecken-Kontrolle: laengste Pause 19 Tage, 2 Spiele, Differenz zu 1230", c["laengste_pause_tage"] == 19 and c["spiele"] == 2 and c["differenz_zu_1230"] == 2 - 1230, c)
    print("\nSELBSTTEST BESTANDEN" if ok else "\nSELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    per, pooled, st, ctl, rt_s = run_all()
    print("\n".join(summary_lines(per, pooled, st, ctl)))
    print(f"\nErgebnisse: {RESULTS / OUT_JSON}\n            {RESULTS / OUT_TXT}\nLaufzeit: {rt_s:.1f} s")

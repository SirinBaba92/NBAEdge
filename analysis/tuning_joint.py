"""
Modell-Tuning, Schritt 3: Heimvorteil und Spread-Skala GEMEINSAM bestimmen, MOV-Daempfung 1,8 / 1,6 / 1,4 (K = 20) damit messen, Test-Saisons 2017-2025,
Bootstrap NACH SAISONS. Nur lesend: liest data/cache und das Pickle (nur Pruefung), schreibt nur analysis/results/tuning_joint.json. Keine API-Calls.
Produktivdateien, Pickle und old_engine_replica.py bleiben unveraendert.

Aufruf (aus dem Projektordner):  venv/bin/python analysis/tuning_joint.py

Verfahren
- Ratings je Variante mit analysis/replica_tunable.py (K = 20, MOV-Faktor 2,2 = Kontrolle / 1,8 / 1,6 / 1,4, hca = 100 im Rating-Update, keine Sommer-Regression).
- Spread-Prognose = s * D0 + h  (D0 = ELO-Differenz ohne Heimvorteil, s = Punkte je ELO, h = Heimvorteil in Punkten). Fuer Test-Saison S werden s UND h GEMEINSAM
  nur aus den Regular-Season-Spielen der Saisons < S bestimmt: Gitter fuer s (0,012 bis 0,060), zu jedem s ist h so gewaehlt, dass der mittlere Fehler (Bias) auf den
  Trainingssaisons genau 0 ist, und unter allen s gewinnt die kleinste Spread-MAE. Brier geht NICHT ein. (Aequivalent in ELO: hca = h / s.)
  Anmerkung: Im Rating-Update bleibt der Heimvorteil bei 100 ELO (nur die Prognose wird neu bestimmt); eine Aenderung von hca in config/ wuerde auch das Update veraendern.
- Test: Saisons 2017-2025 (Parameterwahl immer nur aus Saisons davor; fuer 2017 nur 2015-2016). Fenster: erste 20 Spiele je Team und alle Regular-Season-Spiele.
- Referenz ("Baseline") = Produktivstand (Faktor 50, hca 100 ELO = 2,0 Punkte, MOV 2,2). Zusaetzlich "MOV 2,2 neu kalibriert" als Kontrolle: trennt den Effekt der
  Neukalibrierung von dem der MOV-Daempfung.
- Intervalle: Bootstrap NACH SAISONS (Ziehen ganzer Saisons mit Zuruecklegen, gewichtet mit der Spielzahl; 10 000 Ziehungen) fuer die zusammengefassten Fenster 2017-2025;
  dazu die Differenz je Saison und die Zahl der Saisons mit Verbesserung. Bei nur 9 Saisons sind die Intervalle grob (eher zu schmal).
- Team Total: Heim = (Total + Spread) / 2, Gast = (Total - Spread) / 2; Kalibrierung Ueber/Unter mit Sigma 12,5 auf Test-Linien Prognose(gerundet) -12 ... +12 (+0,5).
- Total: haengt nur an Off/Def, nicht an Rating-Parametern -> Differenz exakt 0 (wird geprueft).
"""
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_common import ROOT, RESULTS, load_games, window  # noqa: E402
import old_engine_replica as old  # noqa: E402
import replica_tunable as rt  # noqa: E402
import tuning_baseline as tb  # noqa: E402
import tuning_grid as tg  # noqa: E402

TEST_SEASONS = list(range(2017, 2026))
ERAS = [("2017-2020", [2017, 2018, 2019, 2020]), ("2021-2022", [2021, 2022]), ("2023-2025", [2023, 2024, 2025])]
SCALES = np.round(np.arange(0.012, 0.0601, 0.001), 4)
VARIANTS = [("MOV 2,2 neu kalibriert (Kontrolle)", 2.2), ("MOV 1,8 neu kalibriert", 1.8), ("MOV 1,6 neu kalibriert", 1.6), ("MOV 1,4 neu kalibriert", 1.4)]
N_BOOT = 10000
METRICS = tg.METRICS
MKEYS = tg.MKEYS
HEAD = {"Sieger": ["s_brier", "s_ll", "s_hit"], "Spread": ["sp_mae", "sp_bias", "sp_hit"], "Total": ["t_mae", "t_bias"],
        "Team Total Heim": ["th_mae", "th_bias", "th_cal"], "Team Total Gast": ["ta_mae", "ta_bias", "ta_cal"]}
HCA_RUN = 100.0


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def fit_joint(d0, margin, season, post, S):
    """Skala s und Heimvorteil h (Punkte) gemeinsam aus Regular-Season-Spielen der Saisons < S: je s ist h so, dass der Bias 0 ist; gewaehlt wird die kleinste MAE."""
    tr = (season < S) & (post == 0)
    d, m = d0[tr], margin[tr]
    best = None
    for s in SCALES:
        h = float((m - s * d).mean())
        mae = float(np.abs(m - s * d - h).mean())
        if best is None or mae < best[0] - 1e-12:
            best = (mae, float(s), h)
    return {"train_mae": best[0], "skala_punkte_je_elo": best[1], "elo_je_punkt": 1.0 / best[1], "hca_punkte": best[2], "hca_elo": best[2] / best[1], "n_train": int(tr.sum())}


def cluster_boot(means, counts, seed=0):
    """means: (Saisons x Kennzahlen) mittlere Differenz je Saison, counts: Spiele je Saison. Rueckgabe (Schaetzer, lo, hi) je Kennzahl."""
    k = len(counts)
    est = (counts[:, None] * means).sum(0) / counts.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, (N_BOOT, k))
    w = counts[idx]
    boots = (w[:, :, None] * means[idx]).sum(1) / w.sum(1)[:, None]
    return np.column_stack([est, np.percentile(boots, 2.5, axis=0), np.percentile(boots, 97.5, axis=0)])


def fmt(t, f=1.0, d=2):
    return f"{t[0] * f:+.{d}f} [{t[1] * f:+.{d}f};{t[2] * f:+.{d}f}]"


def main(write=print):
    T0 = time.perf_counter()
    files = [ROOT / "data" / "elo_model.pkl", ROOT / "models" / "elo.py", ROOT / "config" / "settings.py", ROOT / "analysis" / "old_engine_replica.py"]
    sha_before = {f.name: sha(f) for f in files}
    games = load_games()

    # ---- Vorpruefung
    o_old, _ = old.run(games, **tb.PRODUCTION)
    arr, se0, off0, de0 = rt.run(games)
    same = all(np.allclose(arr[k], o_old[k], atol=1e-9) for k in ("season", "post", "gp_h", "gp_a", "diff", "margin", "hw", "total"))
    chk = tb.check_against_pickle(games, se0, off0, de0)
    write(f"Vorpruefung: Nachbau == old_engine_replica: {same}; == Pickle (24 Teams exakt, 6 mit neueren Spielen): {chk['ok']}")
    if not (same and chk["ok"]):
        write("ABBRUCH: Nachbau passt nicht zur Produktivengine.")
        return 2
    season, post, margin = arr["season"], arr["post"], arr["margin"]
    base = {"arr": arr}
    p0 = np.nan_to_num(tb.walk_forward_probs(arr, TEST_SEASONS), nan=0.5)
    Vb = {"p": p0, "sp": arr["diff"] / tb.SPREAD_FACTOR, "tp": arr["total_pred"]}
    Db = tg.per_game(Vb, base)

    # ---- Varianten
    runs, params = {}, {}
    for name, f in VARIANTS:
        a, _se, _o, _d = rt.run(games, K=20.0, hca=HCA_RUN, mov="cur", mov_factor=f)
        p = np.nan_to_num(tb.walk_forward_probs(a, TEST_SEASONS), nan=0.5)
        d0 = a["diff"] - HCA_RUN
        sp = Vb["sp"].copy()
        params[name] = {}
        for S in TEST_SEASONS:
            fit = fit_joint(d0, margin, season, post, S)
            params[name][S] = fit
            m = season == S
            sp[m] = fit["skala_punkte_je_elo"] * d0[m] + fit["hca_punkte"]
        runs[name] = tg.per_game({"p": p, "sp": sp, "tp": a["total_pred"]}, base)
    t_run = time.perf_counter()
    total_equal = all(np.allclose(D[:, tg.MIDX["t_mae"]], Db[:, tg.MIDX["t_mae"]]) and np.allclose(D[:, tg.MIDX["t_bias"]], Db[:, tg.MIDX["t_bias"]]) for D in runs.values())

    # ---- Masken
    def mask(seasons, early):
        m = np.zeros(len(season), bool)
        for S in seasons:
            m |= window(arr, S, early)
        return m
    pooled = {"alle_2017-25": (TEST_SEASONS, False), "erste20_2017-25": (TEST_SEASONS, True)}
    per_season = {(S, e): window(arr, S, e) for S in TEST_SEASONS for e in (False, True)}

    ctrl_name = VARIANTS[0][0]
    res = {}
    for name, D in runs.items():
        r = {"pooled": {}, "je_saison": {}, "eras": {}}
        diff = D - Db
        for wname, (ss, early) in pooled.items():
            means = np.array([diff[per_season[(S, early)]].mean(axis=0) for S in ss])
            counts = np.array([per_season[(S, early)].sum() for S in ss], float)
            cb = cluster_boot(means, counts)
            absv = np.array([D[per_season[(S, early)]].mean(axis=0) for S in ss])
            absb = np.array([Db[per_season[(S, early)]].mean(axis=0) for S in ss])
            wavg = lambda x: (counts[:, None] * x).sum(0) / counts.sum()
            r["pooled"][wname] = {k: {"diff": [float(cb[i, 0]), float(cb[i, 1]), float(cb[i, 2])], "variante": float(wavg(absv)[i]), "baseline": float(wavg(absb)[i]),
                                      "saisons_besser": int((means[:, i] < 0).sum()) if k in ("s_brier", "s_ll", "sp_mae", "t_mae", "th_mae", "ta_mae", "th_cal", "ta_cal") else int((means[:, i] > 0).sum())}
                                  for i, k in enumerate(MKEYS)}
        for early in (False, True):
            tag = "erste20" if early else "alle"
            r["je_saison"][tag] = {str(S): {k: float(diff[per_season[(S, early)]].mean(axis=0)[i]) for i, k in enumerate(MKEYS)} for S in TEST_SEASONS}
            for en, ss in ERAS:
                m = np.zeros(len(season), bool)
                for S in ss:
                    m |= per_season[(S, early)]
                r["eras"][f"{tag}_{en}"] = {k: float(diff[m].mean(axis=0)[i]) for i, k in enumerate(MKEYS)}
        # Netto-Effekt der MOV-Daempfung: Variante gegen die Kontrolle (gleiche Neukalibrierung, MOV 2,2)
        r["netto_gegen_kontrolle"] = {}
        diff_c = D - runs[ctrl_name]
        for wname, (ss, early) in pooled.items():
            means = np.array([diff_c[per_season[(S, early)]].mean(axis=0) for S in ss])
            counts = np.array([per_season[(S, early)].sum() for S in ss], float)
            cb = cluster_boot(means, counts)
            r["netto_gegen_kontrolle"][wname] = {k: {"diff": [float(cb[i, 0]), float(cb[i, 1]), float(cb[i, 2])], "saisons_besser": int((means[:, i] < 0).sum())} for i, k in enumerate(MKEYS)}
        res[name] = r
    # absoluter Bias und echte Heimmarge je Zeitraum
    abs_bias = {}
    for early in (False, True):
        tag = "erste20" if early else "alle"
        for en, ss in ERAS:
            m = np.zeros(len(season), bool)
            for S in ss:
                m |= per_season[(S, early)]
            abs_bias[f"{tag}_{en}"] = {"echte_heim_marge": float(margin[m].mean()), "baseline": {"spread_bias": float(Db[m][:, tg.MIDX["sp_bias"]].mean()), "spread_mae": float(Db[m][:, tg.MIDX["sp_mae"]].mean())},
                                       **{n: {"spread_bias": float(D[m][:, tg.MIDX["sp_bias"]].mean()), "spread_mae": float(D[m][:, tg.MIDX["sp_mae"]].mean())} for n, D in runs.items()}}
    t_end = time.perf_counter()

    # ------------------------------------------------------------------ Ausgabe
    write("\n=== Gemeinsam bestimmte Parameter (nur aus Saisons < Test-Saison; Kriterium Spread-MAE bei Bias 0 im Training) ===")
    write(f"  Baseline (Produktiv): 50 ELO je Punkt (s = 0,0200), Heimvorteil 2,0 Punkte (= 100 ELO)")
    write(f"  {'Variante':<36}" + "".join(f"{S:>9}" for S in TEST_SEASONS))
    for name, _f in VARIANTS:
        write(f"  {name[:36]:<36}" + "".join(f"{1 / params[name][S]['skala_punkte_je_elo']:>9.1f}" for S in TEST_SEASONS) + "   ELO je Punkt")
        write(f"  {'':<36}" + "".join(f"{params[name][S]['hca_punkte']:>9.2f}" for S in TEST_SEASONS) + "   Heimvorteil in Punkten")
        write(f"  {'':<36}" + "".join(f"{params[name][S]['hca_elo']:>9.0f}" for S in TEST_SEASONS) + "   Heimvorteil in ELO")

    unit = {"s_brier": (1000, "x10^-3"), "s_ll": (1000, "x10^-3"), "s_hit": (100, "pp"), "sp_mae": (1, "Pkt"), "sp_bias": (1, "Pkt"), "sp_hit": (100, "pp"), "t_mae": (1, "Pkt"),
            "t_bias": (1, "Pkt"), "th_mae": (1, "Pkt"), "th_bias": (1, "Pkt"), "th_cal": (1000, "x10^-3"), "ta_mae": (1, "Pkt"), "ta_bias": (1, "Pkt"), "ta_cal": (1000, "x10^-3")}
    names = {k: n for k, _m, n, _f in METRICS}
    for market, mk in HEAD.items():
        write(f"\n--- {market}: Differenz Variante - Baseline [95-%-Intervall, Bootstrap nach Saisons], zusammengefasst 2017-2025 ---")
        for wname, wl in (("alle_2017-25", "ALLE Spiele"), ("erste20_2017-25", "ERSTE 20 Spiele")):
            write(f"  {wl}:  " + "; ".join(f"{names[k]} [{unit[k][1]}]" for k in mk) + "  | Saisons mit Verbesserung (erste Kennzahl)")
            for name, _f in VARIANTS:
                cells = []
                for k in mk:
                    x = res[name]["pooled"][wname][k]["diff"]
                    star = "*" if (x[1] > 0 or x[2] < 0) else " "
                    cells.append(f"{fmt(x, unit[k][0])}{star}")
                sb = res[name]["pooled"][wname][mk[0]]["saisons_besser"]
                write(f"    {name[:36]:<36}" + "  ".join(f"{c:<24}" for c in cells) + f"  {sb}/9")
        if market == "Total":
            write(f"    -> Rating-Parameter aendern den Total nicht; Differenz exakt 0 (geprueft: {total_equal}).")

    write("\n--- Spread-MAE: Differenz je Saison (alle Spiele; negativ = besser), Punkte ---")
    write(f"  {'Variante':<36}" + "".join(f"{S:>8}" for S in TEST_SEASONS))
    for name, _f in VARIANTS:
        write(f"  {name[:36]:<36}" + "".join(f"{res[name]['je_saison']['alle'][str(S)]['sp_mae']:>+8.2f}" for S in TEST_SEASONS))
    write("--- Spread-MAE: Differenz je Saison (erste 20 Spiele) ---")
    for name, _f in VARIANTS:
        write(f"  {name[:36]:<36}" + "".join(f"{res[name]['je_saison']['erste20'][str(S)]['sp_mae']:>+8.2f}" for S in TEST_SEASONS))
    write("\n--- Zeitraeume (nur Differenz, ohne Intervall): Spread-MAE / Team-Total-MAE Heim / Gast / Sieger-Brier x10^-3 ---")
    write(f"  {'Variante':<36}{'Fenster':<20}{'Spread':>8}{'TT Heim':>9}{'TT Gast':>9}{'Brier':>8}{'Spr.-Bias':>11}")
    for name, _f in VARIANTS:
        for tag in ("alle", "erste20"):
            for en, _ss in ERAS:
                x = res[name]["eras"][f"{tag}_{en}"]
                write(f"  {name[:36]:<36}{tag + ' ' + en:<20}{x['sp_mae']:>+8.2f}{x['th_mae']:>+9.2f}{x['ta_mae']:>+9.2f}{x['s_brier'] * 1000:>+8.2f}{x['sp_bias']:>+11.2f}")

    write("\n--- Spread absolut je Zeitraum: Bias (Prognose minus Ergebnis, Punkte) / MAE; echte Heimmarge ---")
    write(f"  {'Fenster':<24}{'echte Marge':>12}{'Baseline':>16}" + "".join(f"{n[:11]:>16}" for n, _f in VARIANTS))
    for key, v in abs_bias.items():
        write(f"  {key:<24}{v['echte_heim_marge']:>+12.2f}{v['baseline']['spread_bias']:>+9.2f}/{v['baseline']['spread_mae']:<6.2f}" +
              "".join(f"{v[n]['spread_bias']:>+9.2f}/{v[n]['spread_mae']:<6.2f}" for n, _f in VARIANTS))
    write("\n--- NETTO-Effekt der MOV-Daempfung: Variante minus Kontrolle (MOV 2,2 neu kalibriert), Bootstrap nach Saisons ---")
    for wname, wl in (("alle_2017-25", "ALLE Spiele"), ("erste20_2017-25", "ERSTE 20 Spiele")):
        write(f"  {wl}:  Spread-MAE [Pkt] | TT Heim-MAE | TT Gast-MAE | Sieger-Brier [x10^-3]  | Saisons mit Verbesserung (Spread)")
        for name, _f in VARIANTS[1:]:
            cells = []
            for k, fac in (("sp_mae", 1), ("th_mae", 1), ("ta_mae", 1), ("s_brier", 1000)):
                x = res[name]["netto_gegen_kontrolle"][wname][k]["diff"]
                cells.append(f"{fmt(x, fac)}{'*' if (x[1] > 0 or x[2] < 0) else ' '}")
            write(f"    {name[:30]:<30}" + "  ".join(f"{c:<24}" for c in cells) + f"  {res[name]['netto_gegen_kontrolle'][wname]['sp_mae']['saisons_besser']}/9")

    # ---- Aussage nach Regel
    write("\n=== Entscheidungsregel (Bootstrap nach Saisons, 2017-2025): Verbesserung = oberes Intervallende der MAE-Differenz < 0 in ALLEN Spielen UND in den ersten 20 Spielen, "
          "Verbesserung in mindestens 6 von 9 Saisons ===")
    verdicts = {}
    for name, _f in VARIANTS:
        v = {}
        for market, k in (("Spread", "sp_mae"), ("Team Total Heim", "th_mae"), ("Team Total Gast", "ta_mae"), ("Total", "t_mae")):
            a, e = res[name]["pooled"]["alle_2017-25"][k], res[name]["pooled"]["erste20_2017-25"][k]
            ok = (a["diff"][2] < 0 and e["diff"][2] < 0 and a["saisons_besser"] >= 6)
            v[market] = {"besser": bool(ok), "alle": a["diff"], "erste20": e["diff"], "saisons_besser": a["saisons_besser"]}
        if name != ctrl_name:                                    # strenger: Netto-Effekt gegen die Kontrolle (nur MOV-Daempfung, ohne Neukalibrierung)
            for market, k in (("Spread", "sp_mae"), ("Team Total Heim", "th_mae"), ("Team Total Gast", "ta_mae")):
                a, e = res[name]["netto_gegen_kontrolle"]["alle_2017-25"][k], res[name]["netto_gegen_kontrolle"]["erste20_2017-25"][k]
                v[market]["netto_besser"] = bool(a["diff"][2] < 0 and e["diff"][2] < 0 and a["saisons_besser"] >= 6)
        verdicts[name] = v
        write(f"  {name[:36]:<36}" + "  ".join(f"{m}: {'JA' if x['besser'] else 'nein'}" + (f" (netto gegen Kontrolle: {'JA' if x.get('netto_besser') else 'nein'})" if 'netto_besser' in x else "") for m, x in v.items()))

    timing = {"laeufe_und_auswahl": round(t_run - T0, 1), "bootstrap": round(t_end - t_run, 1), "gesamt": round(time.perf_counter() - T0, 1)}
    sha_after = {f.name: sha(f) for f in files}
    write(f"\nLaufzeit gesamt {timing['gesamt']} s ({timing})")
    write("SHA vor/nach: " + ("alle unveraendert (" + ", ".join(sha_before) + ")" if sha_before == sha_after else f"ABWEICHUNG {sha_before} -> {sha_after}"))
    out = {"version": 1, "bootstrap": {"art": "nach Saisons (ganze Saisons ziehen, gewichtet mit Spielzahl)", "ziehungen": N_BOOT, "intervall": "95 %", "saisons": len(TEST_SEASONS)},
           "metriken": {k: {"name": n, "einheit_faktor": unit[k][0], "einheit": unit[k][1]} for k, _m, n, _f in METRICS},
           "parameter_je_saison": {n: {str(S): v for S, v in d.items()} for n, d in params.items()}, "ergebnis": res, "entscheidung": verdicts,
           "total_unveraendert": bool(total_equal), "spread_absolut_je_zeitraum": abs_bias, "pruefung": {"nachbau_gleich": bool(same), "pickle": chk["ok"], "sha_vorher": sha_before, "sha_nachher": sha_after}, "laufzeit_sekunden": timing}
    pth = RESULTS / "tuning_joint.json"
    pth.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    write(f"Geschrieben: {pth.relative_to(ROOT)} ({pth.stat().st_size / 1024:.0f} KB)")
    return 0 if sha_before == sha_after else 3


if __name__ == "__main__":
    sys.exit(main())

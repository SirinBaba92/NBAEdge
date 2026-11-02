"""Tagesverlauf der Modellguete (nur lesend, ohne Netz): wird das Modell von Tag zu Tag besser?

  venv/bin/python analysis/trend_tagesverlauf.py

Team-Maerkte: je Spieltag die letzte Version vor dem Anpfiff aus data/tracking/projection_snapshots.json gegen das Ergebnis:
Fehler des erwarteten Abstands/der Punktesumme (Modell gegen Marktlinie), Brier-Wert des Siegers, Trefferquote des Siegers.
Spielerpunkte: Brier-Werte (Buchmacher / Modell roh / Teamabgleich) aus den vorhandenen analysis/results/eval_player_forecasts_<Tag>.txt.
Aendert nichts, schreibt nur auf die Standardausgabe. Kleine Stichproben (wenige Spiele je Tag) schwanken stark: Trend ueber die ganze Zeit zaehlt, nicht ein Tag."""
import json, re, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
snap = json.loads((ROOT / "data/tracking/projection_snapshots.json").read_text())

days = defaultdict(list)
for g in snap["games"].values():
    r, vs = g.get("result"), g.get("versions")
    if not r or not vs:
        continue
    v = vs[-1]
    p = v.get("projection") or {}
    if p.get("exp_spread") is None or p.get("home_win_prob") is None:
        continue
    margin = r["home_points"] - r["away_points"]
    total = r["home_points"] + r["away_points"]
    days[g["game_date"]].append(dict(margin=margin, total=total, es=p["exp_spread"], et=p["exp_total"], ms=p.get("market_spread"), mt=p.get("market_total"),
                                     pw=p["home_win_prob"]))

# Vorzeichen des Abstands: exp_spread und market_spread beziehen sich auf dieselbe Seite; passend zum Ergebnis waehlen
allg = [x for d in days.values() for x in d]
def corr(a, b):
    ma, mb = st.mean(a), st.mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sum((x - ma) ** 2 for x in a) ** .5 * sum((y - mb) ** 2 for y in b) ** .5)
sign = 1 if corr([x["es"] for x in allg], [x["margin"] for x in allg]) > 0 else -1

def rowstats(rs):
    n = len(rs)
    mae_s = st.mean(abs(x["margin"] - sign * x["es"]) for x in rs)
    mae_t = st.mean(abs(x["total"] - x["et"]) for x in rs)
    bs = [x for x in rs if x["ms"] is not None]
    mkt_s = st.mean(abs(x["margin"] - sign * x["ms"]) for x in bs) if bs else None
    bt = [x for x in rs if x["mt"] is not None]
    mkt_t = st.mean(abs(x["total"] - x["mt"]) for x in bt) if bt else None
    brier = st.mean((x["pw"] - (1 if x["margin"] > 0 else 0)) ** 2 for x in rs)
    acc = st.mean(1 if (x["pw"] > .5) == (x["margin"] > 0) else 0 for x in rs)
    bias_t = st.mean(x["et"] - x["total"] for x in rs)
    return n, mae_s, mkt_s, mae_t, mkt_t, brier, acc, bias_t

f = lambda v, w=6, d=1: (f"{v:{w}.{d}f}" if v is not None else " " * (w - 1) + "–")
print("TEAM-MAERKTE (Fehler in Punkten, kleiner ist besser; Brier Sieger: 0,25 = Muenzwurf)")
print("Tag         Spiele  Abstand:Modell Markt | Summe:Modell Markt  Verz.  | Brier  Sieger-Treffer")
cum = []
rows = []
for d in sorted(days):
    n, ms, mk, mt, mkt, br, acc, bi = rowstats(days[d])
    cum += days[d]
    rows.append((d, n, ms, mk, mt, mkt, br, acc, bi))
    print(f"{d}  {n:5d}   {f(ms)} {f(mk)}      | {f(mt)} {f(mkt)} {f(bi,6,1)}  | {br:.3f}  {acc*100:5.0f} %")
n, ms, mk, mt, mkt, br, acc, bi = rowstats(cum)
print(f"gesamt      {n:5d}   {f(ms)} {f(mk)}      | {f(mt)} {f(mkt)} {f(bi,6,1)}  | {br:.3f}  {acc*100:5.0f} %")
half = len(cum) // 2
for name, rs in (("erste Haelfte der Spiele", cum[:half]), ("zweite Haelfte der Spiele", cum[half:])):
    n, ms, mk, mt, mkt, br, acc, bi = rowstats(rs)
    print(f"{name:26s} n={n:3d}  Abstand {ms:.2f} (Markt {mk:.2f})  Summe {mt:.2f} (Markt {mkt:.2f})  Brier {br:.3f}  Treffer {acc*100:.0f} %")
xs = list(range(len(rows)))
for lab, idx in (("Abstandsfehler", 2), ("Summenfehler", 4), ("Brier Sieger", 6)):
    ys = [r[idx] for r in rows]
    mx, my = st.mean(xs), st.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    print(f"Trend {lab}: {slope:+.3f} je Tag (negativ = besser)")

print("\nSPIELERPUNKTE (Brier je Spieltag, kleiner ist besser; Quelle eval_player_forecasts_<Tag>.txt)")
print("Tag         Spieler Zeilen   Buchmacher   Modell roh   Teamabgleich")
pl = []
for p in sorted((ROOT / "analysis/results").glob("eval_player_forecasts_2026-*.txt")):
    t = p.read_text()
    starts = [m.start() for m in re.finditer(r"^Spiele \d+, Spieler gewertet", t, re.M)]
    t = t[:starts[1]] if len(starts) > 1 else t              # die Datei hat zuerst den Tagesblock, danach einen kumulierten Block: nur der Tag zaehlt
    day = p.stem.split("_")[-1]
    m = re.search(r"Spieler gewertet (\d+), Zeilen (\d+)", t)
    b = {k: float(x) for k, x in re.findall(r"(Buchmacher \(inkl\. Marge\)|Modell roh|Modell Teamabgleich)\s+Brier ([0-9.]+)", t)}
    if m and len(b) == 3:
        v = list(b.values())
        pl.append((day, *v))
        print(f"{day}  {m.group(1):>6s} {m.group(2):>6s}   {v[0]:.4f}      {v[1]:.4f}      {v[2]:.4f}")
if pl:
    for k, lab in ((1, "Buchmacher"), (2, "Modell roh"), (3, "Teamabgleich")):
        ys = [r[k] for r in pl]; xs2 = list(range(len(ys))); mx, my = st.mean(xs2), st.mean(ys)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs2, ys)) / sum((x - mx) ** 2 for x in xs2)
        print(f"Mittel {lab:13s} {my:.4f}   Trend {slope:+.4f} je Tag")
    print(f"Tage, an denen Modell roh besser als Buchmacher: {sum(1 for r in pl if r[2] < r[1])} von {len(pl)}; Teamabgleich besser: {sum(1 for r in pl if r[3] < r[1])} von {len(pl)}")

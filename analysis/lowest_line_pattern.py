"""
Muster der NIEDRIGSTEN Linie je Markt (nur lesend, ohne Netz): Welche Chance zeigt die niedrigste Linie, und wie oft trifft sie? Ziel: einen Schwellwert finden.

  venv/bin/python analysis/lowest_line_pattern.py [Pfad/zu/projection_snapshots_YYYY-MM-DD.json]
  Standard: data/tracking/history/projection_snapshots_2026-10-30.json. Ergebnis: Konsole und analysis/results/niedrigste_linie_muster.txt

Je beendetem Spiel mit Ergebnis die letzte Version vor dem Anpfiff (wie analysis/eval_snapshots.py). Je Markt die niedrigste Linie der Tabelle und die Seite, die dort
am sichersten ist, mit ihrer vorhergesagten Chance in %:
  Spread       niedrigste Linie, Seite = Favorit deckt (Margin des Favoriten > Linie)
  Total        niedrigste Linie, Seite = Over
  Team Total   niedrigste Linie je Team (Gast, Heim), Seite = Over
  Moneyline    kein Linien-Markt: Seite = Favorit (Siegchance > 50 %), gewonnen = Favorit hat gewonnen; Chance aus projection.home_win_prob
Push (Treffer genau auf der Linie) zaehlt nicht mit. Gruppiert nach sigmas_version (Prozentwerte verschiedener Versionen werden nie gemischt).
Je Markt: Tabelle je Chance-Stufe (5-Punkte-Schritte) und kumuliert "ab X %" mit Trefferquote und untere Grenze (Wilson, 95 %). Bei < 30 Faellen: Hinweis "zu wenig Daten".
Aendert nichts. Auch eine Liste je Spiel steht im Bericht.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.projection_snapshots import sigmas_version_of

DEFAULT = ROOT / "data" / "tracking" / "history" / "projection_snapshots_2026-10-30.json"
OUT = ROOT / "analysis" / "results" / "niedrigste_linie_muster.txt"
MIN_N = 30
STEP = 5
MARKETS = [("moneyline", "Moneyline (Favorit gewinnt)"), ("spread", "Spread (Favorit deckt, niedrigste Linie)"), ("total", "Total Over (niedrigste Linie)"),
           ("team_away", "Team Total Gast Over (niedrigste Linie)"), ("team_home", "Team Total Heim Over (niedrigste Linie)")]


def wilson_low(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def cases(data: dict) -> list[dict]:
    """[{'markt', 'spiel', 'version', 'linie', 'p', 'hit' (True/False/None=Push)}] aus den letzten Versionen beendeter Spiele."""
    out = []
    for key, g in (data.get("games") or {}).items():
        res, vers = g.get("result"), g.get("versions") or []
        if not res or not vers:
            continue
        v, hp, ap = vers[-1], res["home_points"], res["away_points"]
        sv, name = sigmas_version_of(v), f'{g["game_date"]} {g["away"]} @ {g["home"]}'
        ph = (v.get("projection") or {}).get("home_win_prob")
        if ph is not None and abs(ph - 0.5) > 1e-9:
            fav_home = ph > 0.5
            out.append({"markt": "moneyline", "spiel": name, "version": sv, "linie": None, "p": 100 * max(ph, 1 - ph), "hit": (hp > ap) == fav_home})
        for tk, t in (v.get("tables") or {}).items():
            rows = sorted(t.get("rows") or [], key=lambda r: r["line"])
            if not rows:
                continue
            r = rows[0]
            if tk == "spread":
                fav = t.get("favorite")
                margin = (hp - ap) if fav == "home" else (ap - hp)
                p = r["p_right"] if fav == "home" else r["p_left"]          # links Gast, rechts Heim (wie row_outcome)
                hit = None if abs(margin - r["line"]) < 1e-9 else margin > r["line"]
            else:
                val = {"total": hp + ap, "team_away": ap, "team_home": hp}.get(tk)
                if val is None:
                    continue
                p = r["p_left"]
                hit = None if abs(val - r["line"]) < 1e-9 else val > r["line"]
            out.append({"markt": tk, "spiel": name, "version": sv, "linie": r["line"], "p": float(p), "hit": hit})
    return out


def table(cs: list[dict]) -> list[str]:
    lines = [f"  Faelle: {len(cs)}  (Push: {sum(1 for c in cs if c['hit'] is None)} nicht gezaehlt)"]
    cs = [c for c in cs if c["hit"] is not None]
    if not cs:
        return lines + ["  keine Faelle"]
    lines.append("  Stufe der Chance      Faelle   Treffer   Quote    |  ab dieser Chance kumuliert: Faelle  Quote  untere Grenze (95 %)")
    lo = int(min(c["p"] for c in cs) // STEP * STEP)
    for a in range(lo, 100, STEP):
        b = a + STEP
        s = [c for c in cs if a <= c["p"] < b or (b >= 100 and c["p"] >= a)]
        k = sum(c["hit"] for c in s)
        c_ = [c for c in cs if c["p"] >= a]
        kc = sum(c["hit"] for c in c_)
        left = f"  {a:>3}-{b:<3} %           {len(s):>5}   {k:>5}   " + (f"{100 * k / len(s):5.1f} %" if s else "   -   ")
        right = f"|  ab {a:>3} %: {len(c_):>5}  " + (f"{100 * kc / len(c_):5.1f} %  {100 * wilson_low(kc, len(c_)):5.1f} %" if c_ else "  -") + ("   zu wenig Daten" if 0 < len(c_) < MIN_N else "")
        if s or c_:
            lines.append(left + "   " + right)
    return lines


def main(path: Path = DEFAULT) -> str:
    data = json.loads(Path(path).read_text())
    allc = cases(data)
    out = [f"NIEDRIGSTE LINIE: MUSTER (Quelle {Path(path).name}, {sum(1 for g in data.get('games', {}).values() if g.get('result'))} beendete Spiele mit Ergebnis)", ""]
    for sv in sorted({c["version"] for c in allc}):
        out += [f"=== sigmas_version {sv} ===", ""]
        for mk, label in MARKETS:
            cs = [c for c in allc if c["markt"] == mk and c["version"] == sv]
            if cs:
                out += [f"{label}"] + table(cs) + [""]
    out += ["JE SPIEL (Markt | Linie | Chance | Ergebnis)"]
    for c in sorted(allc, key=lambda c: (c["markt"], c["spiel"])):
        out.append(f'  {c["markt"]:<9} | {c["spiel"]} | Linie {c["linie"] if c["linie"] is not None else "-"} | {c["p"]:.0f} % | ' + {True: "getroffen", False: "verfehlt", None: "Push"}[c["hit"]] + f' | v{c["version"]}')
    text = "\n".join(out) + "\n"
    OUT.write_text(text)
    return text


if __name__ == "__main__":
    print(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT))

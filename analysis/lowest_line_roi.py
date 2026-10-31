"""
TEMPORAER (zum gemeinsamen Ansehen, danach loeschen): Gewinn/Verlust und ROI der niedrigsten Linie je Markt. Nur lesend, ohne Netz.

  venv/bin/python analysis/lowest_line_roi.py [Pfad/zu/projection_snapshots_YYYY-MM-DD.json]
Erweitert analysis/lowest_line_pattern.py um die Betano-Quoten aus data/tracking/pre_match_entries.json (nur Linien, die eingegeben wurden). Einsatz 1 Einheit je Fall:
Treffer = Quote - 1, verfehlt = -1, Push = 0 (Einsatz zurueck, zaehlt nicht in den Einsatz). ROI = Gewinn / Summe der Einsaetze.
Zwei Varianten: A) niedrigste Linie der Tabelle, nur wenn dafuer eine Quote eingegeben ist; B) niedrigste Tabellenlinie MIT eingegebener Quote.
Moneyline: Favorit (Siegchance > 50 %) mit Quote aus winner_incl_ot. Ergebnis: Konsole und analysis/results/niedrigste_linie_roi.txt
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
from data.projection_snapshots import sigmas_version_of
from lowest_line_pattern import DEFAULT, MARKETS, MIN_N, STEP, wilson_low

ENTRIES = ROOT / "data" / "tracking" / "pre_match_entries.json"
OUT = ROOT / "analysis" / "results" / "niedrigste_linie_roi.txt"


def _find(lines, field, value):
    for l in lines or []:
        if l.get(field) is not None and abs(float(l[field]) - value) < 1e-9:
            return l
    return None


def odds_for(entry: dict, tk: str, row: dict, fav: str | None):
    """Quote der sicheren Seite fuer diese Tabellenzeile oder None (Linie nicht eingegeben)."""
    m = (entry or {}).get("markets") or {}
    if tk == "spread":
        sp = m.get("spread") or {}
        if fav == "home":
            l = _find(sp.get("lines"), "line_home", -row["line"]); return None if l is None else l.get("home_odds")
        l = _find(sp.get("lines"), "line_away", -row["line"]); return None if l is None else l.get("away_odds")
    if tk == "total":
        l = _find((m.get("total") or {}).get("lines"), "line", row["line"]); return None if l is None else l.get("over_odds")
    side = "away" if tk == "team_away" else "home"
    l = _find(((m.get("team_totals") or {}).get(side) or {}).get("lines"), "line", row["line"]); return None if l is None else l.get("over_odds")


def result(tk, row, fav, hp, ap):
    if tk == "spread":
        margin = (hp - ap) if fav == "home" else (ap - hp)
        return None if abs(margin - row["line"]) < 1e-9 else margin > row["line"]
    val = {"total": hp + ap, "team_away": ap, "team_home": hp}[tk]
    return None if abs(val - row["line"]) < 1e-9 else val > row["line"]


def cases(data: dict, entries: dict) -> list[dict]:
    out = []
    for key, g in (data.get("games") or {}).items():
        res, vers = g.get("result"), g.get("versions") or []
        if not res or not vers:
            continue
        v, hp, ap, e = vers[-1], res["home_points"], res["away_points"], entries.get(key)
        sv, name = sigmas_version_of(v), f'{g["game_date"]} {g["away"]} @ {g["home"]}'
        ph = (v.get("projection") or {}).get("home_win_prob")
        w = ((e or {}).get("markets") or {}).get("winner_incl_ot") or {}
        if ph is not None and abs(ph - 0.5) > 1e-9 and w.get("home_odds") and w.get("away_odds"):
            fh = ph > 0.5
            out.append({"var": "A", "markt": "moneyline", "spiel": name, "version": sv, "linie": None, "p": 100 * max(ph, 1 - ph), "odds": w["home_odds" if fh else "away_odds"], "hit": (hp > ap) == fh})
        for tk, t in (v.get("tables") or {}).items():
            rows = sorted(t.get("rows") or [], key=lambda r: r["line"])
            if not rows or tk not in ("spread", "total", "team_away", "team_home"):
                continue
            fav = t.get("favorite")
            for var, cand in (("A", rows[:1]), ("B", rows)):
                for r in cand:
                    o = odds_for(e, tk, r, fav)
                    if o is None:
                        continue
                    p = (r["p_right"] if fav == "home" else r["p_left"]) if tk == "spread" else r["p_left"]
                    out.append({"var": var, "markt": tk, "spiel": name, "version": sv, "linie": r["line"], "p": float(p), "odds": float(o), "hit": result(tk, r, fav, hp, ap)})
                    break
    return out


def summary(cs: list[dict]) -> str:
    stake = [c for c in cs if c["hit"] is not None]
    pnl = sum((c["odds"] - 1) if c["hit"] else -1 for c in stake)
    return f"Faelle {len(stake)}, Treffer {sum(c['hit'] for c in stake)}, Gewinn/Verlust {pnl:+.2f} Einh., ROI " + (f"{100 * pnl / len(stake):+.1f} %" if stake else "-")


def main(path: Path = DEFAULT) -> str:
    data = json.loads(Path(path).read_text())
    entries = json.loads(ENTRIES.read_text()).get("entries", {})
    allc = cases(data, entries)
    n_games = sum(1 for g in data.get("games", {}).values() if g.get("result"))
    out = [f"NIEDRIGSTE LINIE: GEWINN/VERLUST UND ROI (Quelle {Path(path).name}, {n_games} beendete Spiele; Einsatz 1 Einheit, Quoten aus pre_match_entries.json) - TEMPORAER", ""]
    for var, title in (("A", "A) niedrigste Tabellenlinie, nur wenn dafuer eine Quote eingegeben ist"), ("B", "B) niedrigste Tabellenlinie MIT eingegebener Quote")):
        if var == "B":
            allc_v = [c for c in allc if c["var"] == "B"]
        else:
            allc_v = [c for c in allc if c["var"] == "A"]
        out += [f"##### {title}", ""]
        for sv in sorted({c["version"] for c in allc_v}):
            out += [f"=== sigmas_version {sv} ===", ""]
            for mk, label in MARKETS:
                cs = [c for c in allc_v if c["markt"] == mk and c["version"] == sv]
                if not cs:
                    continue
                out += [f"{label}", f"  gesamt: {summary(cs)}"]
                lo = int(min(c["p"] for c in cs) // STEP * STEP)
                for a in range(lo, 100, STEP):
                    s = [c for c in cs if c["p"] >= a and c["hit"] is not None]
                    if s:
                        pnl = sum((c["odds"] - 1) if c["hit"] else -1 for c in s)
                        out.append(f"  ab {a:>3} %: Faelle {len(s):>3}, Quote {100 * sum(c['hit'] for c in s) / len(s):5.1f} %, Gewinn/Verlust {pnl:+7.2f}, ROI {100 * pnl / len(s):+6.1f} %"
                                   + ("   zu wenig Daten" if len(s) < MIN_N else ""))
                out.append("")
    out += ["JE FALL (Variante | Markt | Spiel | Linie | Chance | Quote | Ergebnis)"]
    for c in sorted(allc, key=lambda c: (c["var"], c["markt"], c["spiel"])):
        out.append(f'  {c["var"]} | {c["markt"]:<9} | {c["spiel"]} | {c["linie"] if c["linie"] is not None else "-"} | {c["p"]:.0f} % | {c["odds"]:.2f} | ' + {True: "getroffen", False: "verfehlt", None: "Push"}[c["hit"]])
    text = "\n".join(out) + "\n"
    OUT.write_text(text)
    return text


if __name__ == "__main__":
    print(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT))

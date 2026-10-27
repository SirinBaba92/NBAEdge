"""
Wahrscheinlichkeiten je Linie (reine Anzeige in den Score-Projections-Karten; die Projektion wird NICHT veraendert).

Normalverteilung um die projizierten Werte:
  Spread (Margin) um die Endprojektion exp_spread, Total um exp_total, Team Total um den projizierten Team-Score.
Nur halbe Linien sind push-frei. Ganzzahlige Linien (z. B. aus eigenen Eingaben) werden trotzdem ohne Push mit der Normalverteilung
gerechnet (P(X > Linie)); die Wahrscheinlichkeit eines exakten Treffers wird nicht ausgewiesen.

Prozentzahlen: ganze Zahlen, beide Seiten ergeben 100 (rechts = 100 - links), begrenzt auf 1..99 (nie 0 oder 100).
Seiten: Total und Team Totals links Over / rechts Under; Spread links Gast / rechts Heim.
"""
from __future__ import annotations

import math
from statistics import NormalDist

# Streuungen (Standardabweichung in Punkten), Stand 23.10.2026 (sigmas_version "2"). Quelle: analysis/sigma_check.py (Ergebnisse: analysis/results/sigma_check.json),
# gemessen auf 10 777 Regular-Season-Spielen 2017-2025 (Nachbau der ELO-Engine, Walk-forward, Ereignis "Heim deckt / Over trifft", Linien um den Mittelwert):
#   Spread      Log-Loss-Minimum 13,2 (95 %: 13,0 bis 13,6; Fenster a/b/c1/c2: 12,4 / 13,8 / 12,8 / 13,6); Fehler ~normal (Schiefe 0,01, Woelbung +0,46), vom Spread unabhaengig
#   Total       18,6 (18,2 bis 19,0; Fenster 18,6 / 18,8 / 18,8 / 18,2); Schiefe +0,22; Prognose etwas zu eng (Steigung Ergebnis auf Prognose 1,11)
#   Team Total  11,6 (11,4 bis 11,8; Fenster 11,6 / 11,8 / 11,6 / 11,4)
# Vorher (sigmas_version "1"): Spread 10,5 (an die kalibrierte Logistik-Siegwahrscheinlichkeit angepasst, gegen die Ergebnisse zu klein: Kalibrierungs-Steigung 0,78),
# Total 18,0, Team Total 12,5. Der Siegbalken kommt seit Version 2 aus derselben Normalverteilung wie der Spread (win_prob_home), nicht mehr aus der Logistik.
# Hinweis: Gemessen fuer das reine Modell. Produktiv wird exp_total (Gewicht 0,32 bis 0,55) und exp_spread (0,25) mit der Marktlinie gemischt, das senkt den Fehler etwas:
# die Werte sind eher eine Obergrenze. Nachmessen mit den Schnappschuessen nach ca. 300 beendeten Spielen (analysis/eval_snapshots.py).
SPREAD_SIGMA = 13.2
TOTAL_SIGMA = 18.6
TEAM_TOTAL_SIGMA = 11.6
SIGMAS_VERSION = "2"             # wird im Schnappschuss mitgespeichert; fehlt das Feld, gilt Version "1" (10,5 / 18,0 / 12,5)

STAFFEL_STEP = 1.0
STAFFEL_SPREAD_HALF = 2        # Spread: 5 Linien (Hauptlinie +- 2)
STAFFEL_TOTAL_HALF = 3         # Total und Team Totals: 7 Linien (Hauptlinie +- 3)
MIN_SPREAD_LINE = 0.5
P_MIN, P_MAX = 1, 99

_ND = NormalDist()


def round_half(value: float) -> float:
    """Auf 0,5 runden (Haelften weg von null); wie data.pre_match_store.round_half, aber ohne Abhaengigkeit."""
    return math.copysign(math.floor(abs(value) * 2 + 0.5) / 2, value) + 0.0


def prob_above(mean: float, line: float, sigma: float) -> float:
    """P(X > line) fuer X ~ Normal(mean, sigma)."""
    return 1.0 - _ND.cdf((line - mean) / sigma)


def win_prob_home(exp_spread: float, sigma: float = SPREAD_SIGMA) -> float:
    """Siegwahrscheinlichkeit Heim = P(Marge > 0) bei Normalverteilung um den Spread-Mittelwert (positiv = Heim staerker) mit demselben Sigma wie der Spread-Balken.
    Gleiche Verteilung wie spread_rows: der Siegbalken und der Spread-Balken bei Linie 0 stimmen exakt ueberein. Begrenzt auf [MIN_WIN_PROB, MAX_WIN_PROB] (config.settings)."""
    from config.settings import MAX_WIN_PROB, MIN_WIN_PROB
    return min(MAX_WIN_PROB, max(MIN_WIN_PROB, _ND.cdf(float(exp_spread) / sigma)))


def percent_pair(p_left: float) -> tuple[int, int]:
    """Ganzzahlige Prozent (links, rechts), Summe 100, je 1..99."""
    left = min(P_MAX, max(P_MIN, int(math.floor(p_left * 100 + 0.5))))
    return left, 100 - left


def predicted_side(left: int, right: int) -> str | None:
    """'left' oder 'right' (hoehere Prozentzahl), bei 50 : 50 None."""
    return "left" if left > right else "right" if right > left else None


def row_outcome(kind: str, row: dict, favorite: str | None, home_points: int, away_points: int, table_key: str) -> str | None:
    """Ist die in der Zeile vorhergesagte (wahrscheinlichere) Seite eingetreten? 'hit' / 'miss' / 'push' (ganzzahlige Linie, exakter Treffer) / None (50 : 50).
    Total: Gesamtpunkte, Team Total: Punkte des Teams ('team_away' / 'team_home'), Over = links. Spread aus Sicht des Favoriten wie in der Zeile:
    der Favorit 'deckt' mit Margin > X (Linie X); links Gast, rechts Heim."""
    side = row.get("predicted")
    if side is None:
        return None
    if kind == "spread":
        margin = (home_points - away_points) if favorite == "home" else (away_points - home_points)
        x = row["line"]
        if abs(margin - x) < 1e-9:
            return "push"
        fav_covers = margin > x
        fav_side = "right" if favorite == "home" else "left"
        return "hit" if (side == fav_side) == fav_covers else "miss"
    value = {"total": home_points + away_points, "team_away": away_points, "team_home": home_points}[table_key]
    if abs(value - row["line"]) < 1e-9:
        return "push"
    return "hit" if (value > row["line"]) == (side == "left") else "miss"


def staffel(main: float, half: int, step: float = STAFFEL_STEP, min_line: float | None = None) -> list[float]:
    """Feste Staffel um die Hauptlinie: main - half*step ... main + half*step (2*half+1 Linien). Ist min_line gesetzt und liegt die unterste Linie darunter,
    wird das ganze Fenster in Schritten von step nach oben verschoben (nicht gekuerzt): die Linienanzahl bleibt, die Hauptlinie bleibt im Fenster."""
    start = main - half * step
    if min_line is not None and start < min_line - 1e-9:
        start += math.ceil((min_line - start) / step - 1e-9) * step
    return [round(start + i * step, 2) for i in range(2 * half + 1)]


def over_under_rows(mean: float, lines: list[float], main: float | None, sigma: float) -> list[dict]:
    """Zeilen fuer Total/Team Total (Over links, Under rechts), nach Linie aufsteigend."""
    rows = []
    for line in sorted(set(round(float(x), 2) for x in lines)):
        p_over = prob_above(mean, line, sigma)
        left, right = percent_pair(p_over)
        rows.append({"line": line, "p_left": left, "p_right": right, "predicted": predicted_side(left, right),
                     "is_main": main is not None and abs(line - main) < 1e-9, "p_left_raw": p_over})
    return rows


def spread_rows(exp_spread: float, favorite: str, lines: list[float], main: float | None, sigma: float = SPREAD_SIGMA) -> list[dict]:
    """Zeilen fuer den Spread aus Sicht des Marktfavoriten (favorite 'home' oder 'away'). Linie X (Favorit -X / Underdog +X, X kann <= 0 sein):
    P(Favorit gewinnt mit mehr als X Punkten). Links Gast, rechts Heim, nach X aufsteigend. exp_spread: positiv = Heim staerker."""
    margin = float(exp_spread) if favorite == "home" else -float(exp_spread)
    rows = []
    for x in sorted(set(round(float(v), 2) for v in lines)):
        p_fav = _ND.cdf((margin - x) / sigma)
        fav_pct, dog_pct = percent_pair(p_fav)
        left, right = (dog_pct, fav_pct) if favorite == "home" else (fav_pct, dog_pct)
        rows.append({"line": x, "p_left": left, "p_right": right, "predicted": predicted_side(left, right),
                     "is_main": main is not None and abs(x - main) < 1e-9, "p_left_raw": (1.0 - p_fav) if favorite == "home" else p_fav})
    return rows


def team_main_from_total_spread(total: float | None, spread: float | None) -> dict | None:
    """Rechnerische Team-Total-Hauptlinien aus Total und Spread (positiv = Heim Favorit): Heim = (Total + Spread) / 2, Gast = (Total - Spread) / 2,
    auf halbe Zahlen gerundet. Fehlt Total oder Spread: None."""
    if not total or spread is None:
        return None
    return {"home": round_half((float(total) + float(spread)) / 2), "away": round_half((float(total) - float(spread)) / 2)}


# ------------------------------------------------------------------------------ Tabellen einer Karte
def build_line_tables(proj: dict, entry: dict | None) -> dict | None:
    """Alle vier Tabellen einer Karte aus der Projektion (proj: Ergebnis von compute_projection + market_lines) und den eigenen Eintraegen
    (entry: Pre-Match-Eintrag des Spiels oder None). Rueckgabe {'spread','total','team_away','team_home': {...}} oder None ohne market_lines.
    Je Tabelle: {'kind': 'spread'|'over_under', 'rows': [...], 'source': 'eigene Eingabe'|'Staffel', 'favorite' (nur Spread), 'note': Text oder None}."""
    ml = proj.get("market_lines")
    if not ml:
        return None
    from data import pre_match_store as store
    exp_spread, exp_total = float(proj["exp_spread"]), float(proj["exp_total"])
    out = {}

    # ---- Spread
    fav, table = None, {"kind": "spread", "rows": [], "source": None, "favorite": None, "note": None}
    own = store.active_spread_lines(entry)
    own_main = next((l for l in own if l.get("id") == "main"), None)
    if own_main is not None:
        fav = "home" if own_main["line_home"] < 0 else "away" if own_main["line_home"] > 0 else ("home" if exp_spread >= 0 else "away")
        sign = -1.0 if fav == "home" else 1.0
        xs = [sign * l["line_home"] + 0.0 for l in own]
        main_x = sign * own_main["line_home"] + 0.0
        table.update(rows=spread_rows(exp_spread, fav, xs, main_x), source="eigene Eingabe", favorite=fav)
    elif ml["spread"]["line"] is not None:
        s = float(ml["spread"]["line"])
        fav = "home" if s > 0 else "away" if s < 0 else ("home" if exp_spread >= 0 else "away")
        main_x = max(MIN_SPREAD_LINE, round_half(abs(s)))
        table.update(rows=spread_rows(exp_spread, fav, staffel(main_x, STAFFEL_SPREAD_HALF, min_line=MIN_SPREAD_LINE), main_x), source="Staffel", favorite=fav)
    else:
        table["note"] = "keine Linie"
    out["spread"] = table

    # ---- Total
    table = {"kind": "over_under", "rows": [], "source": None, "note": None}
    own = store.active_total_lines(entry)
    own_main = next((l for l in own if l.get("id") == "main"), None)
    if own_main is not None:
        table.update(rows=over_under_rows(exp_total, [l["line"] for l in own], own_main["line"], TOTAL_SIGMA), source="eigene Eingabe")
    elif ml["total"]["line"] is not None:
        main = round_half(float(ml["total"]["line"]))
        table.update(rows=over_under_rows(exp_total, staffel(main, STAFFEL_TOTAL_HALF), main, TOTAL_SIGMA), source="Staffel")
    else:
        table["note"] = "keine Linie"
    out["total"] = table

    # ---- Team Totals (Gast, Heim)
    derived = team_main_from_total_spread(ml["total"]["line"], ml["spread"]["line"])
    for side, score in (("away", proj["away_score"]), ("home", proj["home_score"])):
        table = {"kind": "over_under", "rows": [], "source": None, "note": None, "derived": False}
        own = store.team_total_lines(entry, side)
        own_main = next((l for l in own if l.get("id") == "main"), None)
        res = ml.get(f"team_total_{side}") or {}
        if own_main is not None:
            table.update(rows=over_under_rows(float(score), [l["line"] for l in own], own_main["line"], TEAM_TOTAL_SIGMA), source="eigene Eingabe")
        else:
            if res.get("line") is not None:
                main = round_half(float(res["line"]))
            elif derived is not None:
                main, table["derived"] = derived[side], True
            else:
                main = None
            if main is None:
                table["note"] = "keine Linie"
            else:
                table.update(rows=over_under_rows(float(score), staffel(main, STAFFEL_TOTAL_HALF), main, TEAM_TOTAL_SIGMA), source="Staffel")
                if table["derived"]:
                    table["note"] = "Hauptlinie rechnerisch aus Total und Spread (kein Marktwert)"
        out[f"team_{side}"] = table
    return out

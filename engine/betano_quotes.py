"""
Betano-Quoten fuer die Karten im Tab Score Projections (reine Anzeige-Hilfen; NUR LESEND, keine Wahrscheinlichkeit, keine Prognose und keine gespeicherte Datei wird veraendert).

Quelle: die gespeicherten Pre-Match-Eintraege (data/pre_match_store.py, data/tracking/pre_match_entries.json; die App reicht den Eintrag eines Spiels als `entry` an die Karte). Gezeigt werden nur Quoten
mit bookmaker == "Betano" (nie Odds-API-Quoten anderer Anbieter). Fehlt eine Quote, ist das Ergebnis None (die Anzeige bleibt leer).

Zuordnung (Heim/Gast und Vorzeichen):
 Sieger: home_odds = Quote des Heimteams, away_odds = Quote des Gastteams.
 Spread: gespeichert je Linie aus Heim-Sicht (line_home = Handicap des Heimteams, home_odds fuer Heim mit line_home, away_odds fuer Gast mit -line_home). Die Zeile der Karte steht aus Sicht des Favoriten:
   Linie X, Favorit -X / Aussenseiter +X. Ist der Favorit das Heimteam, gehoert die Zeile zu line_home = -X, sonst (Favorit = Gast) zu line_home = +X. Orange (vorhergesagt) rechts = Heim -> home_odds, links = Gast -> away_odds.
 Total / Team Total: Linie gleich der Zeilenlinie; orange links = Over -> over_odds, rechts = Under -> under_odds. Team Total je Seite ('away'/'home') wie in engine/line_probabilities.build_line_tables.
 Bei 50 : 50 (keine orange Seite) und ohne gespeicherte Quote: None.
"""
from __future__ import annotations

from data import pre_match_store as store

TOL = 1e-9


def is_betano(bookmaker) -> bool:
    return str(bookmaker or "").strip().casefold() == "betano"


def odds_text(value) -> str | None:
    """'5,50' (Komma, 2 Nachkommastellen); None bei fehlender oder unbrauchbarer Quote."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v or v <= 1.0 else f"{v:.2f}".replace(".", ",")


def winner_quotes(entry: dict | None) -> dict | None:
    """{'away': '5,50', 'home': '1,07'} (Texte) aus der gespeicherten Betano-Sieger-Quote; None ohne Betano-Quote."""
    m = ((entry or {}).get("markets") or {}).get(store.WINNER)
    if not isinstance(m, dict) or not is_betano(m.get("bookmaker")):
        return None
    out = {"away": odds_text(m.get("away_odds")), "home": odds_text(m.get("home_odds"))}
    return out if (out["away"] or out["home"]) else None


def _find(lines: list[dict], key: str, value: float) -> dict | None:
    return next((l for l in lines if is_betano(l.get("bookmaker")) and l.get(key) is not None and abs(float(l[key]) - float(value)) < TOL), None)


def row_quote_text(entry: dict | None, table_key: str, table: dict, row: dict) -> str | None:
    """Betano-Quote der orange hinterlegten (vorhergesagten) Seite einer Zeile als Text, sonst None.
    table_key: 'spread' | 'total' | 'team_away' | 'team_home'; table: Tabelle aus build_line_tables (fuer den Spread mit 'favorite'); row: Zeile mit 'line' und 'predicted'."""
    if not entry or row.get("predicted") is None:
        return None
    side = row["predicted"]
    if table_key == "spread":
        fav = table.get("favorite")
        if fav not in ("home", "away"):
            return None
        x = float(row["line"])
        line_home = -x if fav == "home" else x
        ln = _find(store.active_spread_lines(entry), "line_home", line_home)
        return odds_text(None if ln is None else ln.get("home_odds" if side == "right" else "away_odds"))
    if table_key == "total":
        lines = store.active_total_lines(entry)
    elif table_key in ("team_away", "team_home"):
        lines = store.team_total_lines(entry, table_key.split("_", 1)[1])
    else:
        return None
    ln = _find(lines, "line", float(row["line"]))
    return odds_text(None if ln is None else ln.get("over_odds" if side == "left" else "under_odds"))

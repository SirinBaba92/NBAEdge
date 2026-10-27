"""
Sicherheitsstufen fuer die Karten im Tab Score Projections (reine Anzeige-Hilfen, KEINE Wahrscheinlichkeit und keine Prognose wird veraendert).

Mindestquote = 1 / (Chance - SAFETY_DISCOUNT), auf 2 Nachkommastellen (kaufmaennisch) gerundet. Die Chance ist die UNGERUNDETE Modell-Chance der Seite mit der hoeheren Chance
(die im Balken orange hinterlegte Seite); angezeigt wird nur bei einer Chance von mindestens 50 %. Sieger-Zeichen: Favorit mit Siegchance >= WINNER_MIN_PROB "erfuellt",
>= WINNER_STRONG_PROB zusaetzlich "(stark)", darunter grau. Alle Schwellen stehen in config/settings.py (SAFETY_DISCOUNT, WINNER_MIN_PROB, WINNER_STRONG_PROB).
Grundlage der Schwellen: analysis/reports/threshold_test.txt. Die Mindestquote ist keine Wettempfehlung: Bietet der Wettschein weniger, lohnt die Wette nach diesem Mass nicht.
"""
from __future__ import annotations

import math

from config import settings

EPS = 1e-9
NBSP = "\xa0"


def min_odds(chance: float | None, discount: float | None = None) -> float | None:
    """Mindestquote zur Chance (0..1); None, wenn die Chance fehlt, unter 50 % liegt oder der Abschlag sie aufbraucht."""
    if chance is None:
        return None
    d = settings.SAFETY_DISCOUNT if discount is None else discount
    p = float(chance)
    if p < 0.5 - EPS or p - d <= 0:
        return None
    return math.floor(100.0 / (p - d) + 0.5 + EPS) / 100.0


def odds_text(value: float | None) -> str | None:
    """'1,61' (Komma, 2 Nachkommastellen) oder None."""
    return None if value is None else f"{value:.2f}".replace(".", ",")


def row_chance(row: dict) -> float | None:
    """Ungerundete Chance der orange hinterlegten (vorhergesagten) Seite einer Zeile; None bei 50 : 50 nach Rundung oder ohne ungerundeten Wert (gespeicherte Schnappschuss-Zeilen)."""
    side, raw = row.get("predicted"), row.get("p_left_raw")
    if side is None or raw is None:
        return None
    return float(raw) if side == "left" else 1.0 - float(raw)


def row_min_odds_text(row: dict) -> str | None:
    return odds_text(min_odds(row_chance(row)))


def winner_sign(p_fav: float | None) -> dict:
    """Sieger-Zeichen fuer den Favoriten mit der ungerundeten Siegchance p_fav. level: 'strong' (ab WINNER_STRONG_PROB), 'ok' (ab WINNER_MIN_PROB), 'low' (darunter).
    text: Anzeigetext mit geschuetztem Leerzeichen vor dem Prozentzeichen."""
    lo, strong = settings.WINNER_MIN_PROB, settings.WINNER_STRONG_PROB
    pct = lambda x: f"{round(x * 100)}{NBSP}%"
    p = None if p_fav is None else float(p_fav)
    if p is None or p < lo - EPS:
        return {"level": "low", "min_odds": None, "text": f"Sieger unter {pct(lo)}"}
    odds = odds_text(min_odds(p))
    if p >= strong - EPS:
        return {"level": "strong", "min_odds": odds, "text": f"Sieger ab {pct(lo)}: erfüllt · Mindestquote {odds} (stark)"}
    return {"level": "ok", "min_odds": odds, "text": f"Sieger ab {pct(lo)}: erfüllt · Mindestquote {odds}"}


def note_text() -> str:
    """Erklaerzeile unter den Expandern."""
    pp = round(settings.SAFETY_DISCOUNT * 100)
    return f"Mindestquote = 1 geteilt durch (Chance minus {pp} Prozentpunkte). Bietet der Wettschein weniger, lass die Wette aus."

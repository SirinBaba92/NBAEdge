"""
Wettstatus (Baustein 2): reine Funktionen ohne Streamlit und ohne I/O.

Stufen (Grenzen aus config.settings): Gewonnen / Verloren (entschieden), sonst nach der Wahrscheinlichkeit, dass die Wette durchgeht:
  Auf Kurs  p > 65 %  (gruen)       Offen  35 % <= p <= 65 %  (gelb)       In Gefahr  10 % <= p < 35 %  (orange)       Kaum noch moeglich  p < 10 %  (rot)
Vor dem Anpfiff: "Wartet auf Anpfiff". Gewonnen sofort bei Over (Total, Team Total), sobald der Stand die Linie uebersteigt; Spread und Sieger erst am Ende.
Ganzzahlige Linien: Gleichstand mit der Linie zaehlt als nicht gewonnen (keine Rueckzahlung).
"""
from __future__ import annotations

from dataclasses import dataclass

from config.settings import LIVE_STATUS_DANGER, LIVE_STATUS_HOPELESS, LIVE_STATUS_ON_TRACK

MARKETS = ("winner", "spread", "total", "team_total_home", "team_total_away")
WON, LOST, ON_TRACK, OPEN, DANGER, HOPELESS, WAITING = "Gewonnen", "Verloren", "Auf Kurs", "Offen", "In Gefahr", "Kaum noch möglich", "Wartet auf Anpfiff"
COLORS = {WON: "gruen", ON_TRACK: "gruen", OPEN: "gelb", DANGER: "orange", HOPELESS: "rot", LOST: "rot", WAITING: "grau"}


@dataclass(frozen=True)
class BetStatus:
    label: str
    color: str
    probability: float | None        # Chance, dass die Wette durchgeht (None: noch nicht gestartet ohne Anker)
    decided: bool                    # Gewonnen oder Verloren
    won: bool | None                 # True/False wenn entschieden, sonst None


def status_from_probability(p: float) -> str:
    """Stufe nach Wahrscheinlichkeit: Grenzen 65 / 35 / 10 %. Genau 65 % und 35 % zaehlen als Offen, genau 10 % als In Gefahr."""
    if p > LIVE_STATUS_ON_TRACK:
        return ON_TRACK
    if p >= LIVE_STATUS_DANGER:
        return OPEN
    if p >= LIVE_STATUS_HOPELESS:
        return DANGER
    return HOPELESS


def bet_probability(proj, bet: dict) -> float:
    """Chance, dass die Wette durchgeht. bet: {'market', 'side' (home/away), 'line'}; Total und Team Total sind immer Over."""
    m = bet["market"]
    if m == "winner":
        return proj.p_winner(bet["side"])
    if m == "spread":
        return proj.p_spread(bet["side"], float(bet["line"]))
    if m == "total":
        return proj.p_over_total(float(bet["line"]))
    if m == "team_total_home":
        return proj.p_over_team("home", float(bet["line"]))
    if m == "team_total_away":
        return proj.p_over_team("away", float(bet["line"]))
    raise ValueError(f"unbekannter Markt: {m}")


def decided_result(bet: dict, home_pts: int, away_pts: int, final: bool) -> bool | None:
    """True/False, wenn die Wette entschieden ist, sonst None. Over (Total/Team Total): sofort gewonnen, sobald der Stand die Linie uebersteigt; sonst erst am Ende. Spread/Sieger: erst am Ende."""
    m = bet["market"]
    if m in ("total", "team_total_home", "team_total_away"):
        pts = {"total": home_pts + away_pts, "team_total_home": home_pts, "team_total_away": away_pts}[m]
        if pts > float(bet["line"]):
            return True
        return False if final else None
    if not final:
        return None
    d = (home_pts - away_pts) * (1 if bet["side"] == "home" else -1)
    if m == "winner":
        return d > 0
    return d + float(bet["line"]) > 0


def evaluate_bet(bet: dict, proj, started: bool = True) -> BetStatus:
    """Status einer Wette aus Hochrechnung (LiveProjection) und Spielzustand. started=False: vor dem Anpfiff."""
    p = bet_probability(proj, bet)
    if not started:
        return BetStatus(WAITING, COLORS[WAITING], p, False, None)
    res = decided_result(bet, proj.home_pts, proj.away_pts, proj.final)
    if res is not None:
        return BetStatus(WON if res else LOST, COLORS[WON if res else LOST], 1.0 if res else 0.0, True, res)
    label = status_from_probability(p)
    return BetStatus(label, COLORS[label], p, False, None)


def profit(bet: dict, status: BetStatus) -> float | None:
    """Gewinn/Verlust nur fuer abgerechnete Wetten: gewonnen = Einsatz * (Quote - 1), verloren = -Einsatz; offen = None."""
    if not status.decided:
        return None
    stake = float(bet.get("stake") or 0)
    return round(stake * (float(bet["odds"]) - 1.0), 2) if status.won else -round(stake, 2)

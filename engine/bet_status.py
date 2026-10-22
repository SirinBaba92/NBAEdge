"""
Wettstatus (Baustein 2): reine Funktionen ohne Streamlit und ohne I/O.

Stufen (Grenzen aus config.settings): Gewonnen / Verloren (entschieden), sonst nach der Wahrscheinlichkeit, dass die Wette durchgeht:
  Auf Kurs  p > 65 %  (gruen)       Offen  35 % <= p <= 65 %  (gelb)       In Gefahr  10 % <= p < 35 %  (orange)       Kaum noch moeglich  p < 10 %  (rot)
Vor dem Anpfiff: "Wartet auf Anpfiff". Gewonnen sofort bei Over (Total, Team Total), sobald der Stand die Linie uebersteigt; Spread und Sieger erst am Ende.
Under (Total, Team Total): sofort VERLOREN, sobald der Stand die Linie erreicht oder uebersteigt (Punkte koennen nur zunehmen), gewonnen erst am Ende (Stand unter der Linie).
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


_TEAM_TOTALS = {"total": None, "team_total_home": "home", "team_total_away": "away"}


def _points(market: str, home_pts: int, away_pts: int) -> int:
    return {"total": home_pts + away_pts, "team_total_home": home_pts, "team_total_away": away_pts}[market]


def bet_probability(proj, bet: dict) -> float:
    """Chance, dass die Wette durchgeht. bet: {'market', 'side', 'line'}; Total und Team Total: side 'over' (Standard) oder 'under'."""
    m = bet["market"]
    if m == "winner":
        return proj.p_winner(bet["side"])
    if m == "spread":
        return proj.p_spread(bet["side"], float(bet["line"]))
    if m in _TEAM_TOTALS:
        line = float(bet["line"])
        if m == "total":
            p_over = proj.p_over_total(line)
        else:
            p_over = proj.p_over_team(_TEAM_TOTALS[m], line)
        if bet.get("side") == "under":
            pts = _points(m, proj.home_pts, proj.away_pts)
            if proj.final or pts >= line:                        # Under: nur bei Stand unter der Linie am Ende
                return 1.0 if (proj.final and pts < line) else 0.0
            return 1.0 - p_over
        return p_over
    raise ValueError(f"unbekannter Markt: {m}")


def decided_result(bet: dict, home_pts: int, away_pts: int, final: bool) -> bool | None:
    """True/False, wenn die Wette entschieden ist, sonst None. Over (Total/Team Total): sofort gewonnen, sobald der Stand die Linie uebersteigt, sonst erst am Ende.
    Under: sofort verloren, sobald der Stand die Linie erreicht, sonst erst am Ende gewonnen. Spread/Sieger: erst am Ende."""
    m = bet["market"]
    if m in _TEAM_TOTALS:
        pts, line = _points(m, home_pts, away_pts), float(bet["line"])
        if bet.get("side") == "under":
            if pts >= line:
                return False
            return True if final else None
        if pts > line:
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


# ------------------------------------------------------------------------------ Spieler-Wetten (Punkte, "mindestens N Punkte", immer Over)
P_WAITING, P_RUNNING, P_WON, P_LOST, P_DNP, P_UNSURE, P_NODATA = "wartet", "laeuft", "gewonnen", "verloren", "nicht_gespielt", "unsicher", "keine_daten"
DNP_LABEL = "Nicht gespielt, Einsatz meist zurück, bitte prüfen"
UNSURE_LABEL = "Spiel beendet, Spielerdaten älter als der Endstand: bitte prüfen"


@dataclass(frozen=True)
class PlayerBetStatus:
    state: str                       # wartet | laeuft | gewonnen | verloren | nicht_gespielt | unsicher | keine_daten
    label: str
    color: str                       # gruen / gelb / orange / rot / grau
    decided: bool                    # gewonnen oder verloren (nicht gespielt und unsicher sind NICHT entschieden)
    won: bool | None
    points: int | None               # aktuelle Punkte
    needed: int | None               # noch noetige Punkte bis zum Meilenstein
    minutes: float | None
    fouls: int | None
    player_status: str | None        # spielt | bank | nicht gespielt
    probability: float | None = None  # Live-Chance: kommt in Baustein P4, das Feld ist vorbereitet


def player_bet_status(bet: dict, player, started: bool, final: bool, complete: bool) -> PlayerBetStatus:
    """Status einer Spieler-Wette (Meilenstein N = mindestens N Punkte). player: PlayerLive-aehnlich (points, minutes, fouls, status) oder None.
    started/final: Spielzustand laut Scoreboard; complete: die Spielerpunkte sind aktuell (Boxscore-Teampunkte == Stand), sonst darf nach Spielende nichts als verloren gelten.
    Gewonnen sofort bei Punkte >= N. Verloren erst nach Spielende und mit aktuellem Boxscore. Nicht gespielt: Spiel beendet und 0 Minuten (kein Gewinn, kein Verlust)."""
    n = int(bet["milestone"])
    if not started and not final:
        return PlayerBetStatus(P_WAITING, WAITING, COLORS[WAITING], False, None, None, n, None, None, None)
    if player is None:
        if final and complete:
            return PlayerBetStatus(P_DNP, DNP_LABEL, "grau", False, None, 0, n, 0.0, 0, "nicht gespielt")
        label = "Keine Spielerdaten (Boxscore noch nicht geholt oder Spieler nicht im Boxscore)"
        return PlayerBetStatus(P_NODATA, label, "grau", False, None, None, n, None, None, None)
    pts, mins, fouls, pst = int(player.points), float(player.minutes), int(player.fouls), player.status
    if pts >= n:
        return PlayerBetStatus(P_WON, WON, COLORS[WON], True, True, pts, 0, mins, fouls, pst)
    needed = n - pts
    if final:
        if not complete:
            return PlayerBetStatus(P_UNSURE, UNSURE_LABEL, "orange", False, None, pts, needed, mins, fouls, pst)
        if mins <= 0:
            return PlayerBetStatus(P_DNP, DNP_LABEL, "grau", False, None, pts, needed, mins, fouls, "nicht gespielt")
        return PlayerBetStatus(P_LOST, LOST, COLORS[LOST], True, False, pts, needed, mins, fouls, pst)
    return PlayerBetStatus(P_RUNNING, f"Läuft: {pts} von {n} Punkten, noch {needed}", "gelb", False, None, pts, needed, mins, fouls, pst)


def player_profit(bet: dict, status: PlayerBetStatus) -> float | None:
    """Gewinn/Verlust nur fuer gewonnene oder verlorene Wetten mit Quote und Einsatz; nicht gespielt, unsicher, offen: None."""
    if not status.decided or bet.get("odds") is None or bet.get("stake") is None:
        return None
    stake = float(bet["stake"])
    return round(stake * (float(bet["odds"]) - 1.0), 2) if status.won else -round(stake, 2)

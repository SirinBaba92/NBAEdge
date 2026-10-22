"""
Ein einziger Zustand fuer Spielphase und Uhr (ersetzt spaeter die vier Uhr-Funktionen in live.py, live_context.py, live_dashboard.py, replay.py).

Eingabe: eine Spielzeile des NBA-Scoreboards (gameStatus 1/2/3, gameStatusText, period, gameClock "PT05M23.00S").
Wichtig: Eine LEERE Uhr bei laufendem Spiel ist KEIN "12:00". Sie bedeutet Periodenende bzw. Pause (Halbzeit, Viertelpause, Ende der regulaeren Zeit).
Solche Zeilen bekommen seconds_left = 0 und clock_missing = True, ausser der Statustext erklaert die leere Uhr ("Halftime", "End of ...").

Phasen: PRE, Q1..Q4 (Viertel laeuft), BREAK (Viertelpause Q1->Q2, Q3->Q4), HALFTIME, REGULAR_END (Q4 vorbei, noch nicht FINAL, ggf. Verlaengerung),
OT (Verlaengerung laeuft, ot_number 1, 2, ...), FINAL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

REG_PERIODS = 4
QUARTER_SECONDS = 12 * 60
OT_SECONDS = 5 * 60
REG_SECONDS = REG_PERIODS * QUARTER_SECONDS

PRE, Q1, Q2, Q3, Q4 = "PRE", "Q1", "Q2", "Q3", "Q4"
BREAK, HALFTIME, REGULAR_END, OT, FINAL = "BREAK", "HALFTIME", "REGULAR_END", "OT", "FINAL"
QUARTER_PHASES = {1: Q1, 2: Q2, 3: Q3, 4: Q4}

_ISO = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")


def parse_clock(raw) -> float | None:
    """Restzeit der Periode in Sekunden. None = keine Angabe (leer, None, nicht lesbar). 'PT05M23.00S', '5:23', '12.5' (Sekunden) und Zahlen werden gelesen."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    text = str(raw).strip()
    if not text:
        return None
    m = _ISO.match(text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        try:
            return max(0.0, int(minutes) * 60 + float(seconds))
        except ValueError:
            return None
    try:
        return max(0.0, float(text))
    except ValueError:
        return None


@dataclass(frozen=True)
class GameClock:
    phase: str                  # PRE | Q1..Q4 | BREAK | HALFTIME | REGULAR_END | OT | FINAL
    status: int                 # 1 = vor dem Anpfiff, 2 = laeuft, 3 = beendet
    period: int                 # 0 vor dem Anpfiff, 1..4 regulaer, 5.. Verlaengerung
    seconds_left: float | None  # Restzeit der aktuellen Periode; 0 bei Pause/Ende; None nur vor dem Anpfiff nicht gesetzt (dort volle Periode)
    elapsed_regulation_s: float  # gespielte Sekunden der regulaeren Zeit (0..2880)
    ot_number: int              # 0 = keine Verlaengerung (bisher), 1 = erste ...
    ot_elapsed_s: float         # gespielte Sekunden aller Verlaengerungen
    clock_missing: bool         # Uhr war leer, ohne dass der Statustext es erklaert (Hinweis fuer Qualitaetsflags)
    running: bool               # True nur, wenn die Uhr wirklich laeuft (Viertel/Verlaengerung mit Restzeit > 0)

    @property
    def is_live(self) -> bool:
        return self.status == 2

    @property
    def is_final(self) -> bool:
        return self.status == 3

    @property
    def elapsed_total_s(self) -> float:
        return self.elapsed_regulation_s + self.ot_elapsed_s


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _status_code(status, text: str, period: int) -> int:
    code = _int(status, 0)
    if code in (1, 2, 3):
        return code
    low = text.lower()
    if "final" in low:
        return 3
    return 2 if period >= 1 else 1


def build_game_clock(status=None, status_text="", period=0, clock=None) -> GameClock:
    """Phase und Zeitstand aus den Rohfeldern. status = gameStatus (1/2/3) oder None (dann aus Text und Periode abgeleitet)."""
    text = str(status_text or "")
    low = text.lower()
    period = max(0, _int(period))
    code = _status_code(status, text, period)
    left = parse_clock(clock)

    if code == 1 or (period == 0 and code != 3):
        return GameClock(PRE, 1, 0, float(QUARTER_SECONDS), 0.0, 0, 0.0, False, False)

    if code == 3:
        ot = max(0, period - REG_PERIODS)
        return GameClock(FINAL, 3, max(period, REG_PERIODS), 0.0, float(REG_SECONDS), ot, float(ot * OT_SECONDS), False, False)

    explained = "half" in low or low.startswith("end")
    missing = left is None
    seconds = 0.0 if missing else left

    if period <= REG_PERIODS:
        elapsed = period * QUARTER_SECONDS - min(seconds, QUARTER_SECONDS)
        if "half" in low:
            return GameClock(HALFTIME, 2, 2, 0.0, float(2 * QUARTER_SECONDS), 0, 0.0, False, False)
        if seconds <= 0:                                   # Periodenende, Pause oder leere Uhr
            phase = HALFTIME if period == 2 else REGULAR_END if period == REG_PERIODS else BREAK
            return GameClock(phase, 2, period, 0.0, float(period * QUARTER_SECONDS), 0, 0.0, missing and not explained, False)
        return GameClock(QUARTER_PHASES[period], 2, period, seconds, float(elapsed), 0, 0.0, False, True)

    ot = period - REG_PERIODS
    in_ot = OT_SECONDS - min(seconds, OT_SECONDS)
    ot_elapsed = (ot - 1) * OT_SECONDS + in_ot
    return GameClock(OT, 2, period, seconds, float(REG_SECONDS), ot, float(ot_elapsed), missing and not explained, seconds > 0)


def from_scoreboard_game(game: dict) -> GameClock:
    """Spielzeile des NBA-Scoreboards (todaysScoreboard_00.json): gameStatus, gameStatusText, period, gameClock."""
    return build_game_clock(game.get("gameStatus"), game.get("gameStatusText"), game.get("period"), game.get("gameClock"))


def from_simple_game(game: dict) -> GameClock:
    """Vereinfachte Spielzeile aus data/nba_live.fetch_live_scoreboard: status (Text), period, clock."""
    return build_game_clock(game.get("status_code"), game.get("status"), game.get("period"), game.get("clock"))

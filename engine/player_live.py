"""
Live-Chance fuer Spieler-Wetten (Punkte, "mindestens N", Over), Baustein P4. Reine Logik, kein Netz, schreibt nichts. UNGEPRUEFT: einfache feste Abschlaege der ersten Version, noch nicht gegen
Ergebnisse geprueft (Version LIVE_VERSION, alle Konstanten in LIVE_CONSTANTS).

Methode
1. Restzeit des Spiels R (Sekunden): Viertel 1 bis 4 = Rest des Viertels + volle weitere Viertel, Verlaengerung = Rest der laufenden Verlaengerung; Gleichstand am Ende der regulaeren Zeit = 5 Minuten Verlaengerung.
2. Erwartete Restminuten des Spielers: Anteil seiner Spielzeit am Spiel (Vorab-Minuten mu0 / 48) mal Restzeit, dann
   - Blowout: Erwartungsfaktor F der gemessenen Minutenkurve (engine/player_forecast.BLOWOUT_CURVE) fuer den Endabstand Normal(aktueller Abstand, Streuung der Restzeit). Ab F < BLOWOUT_MIN_FACTOR
     (merklicher Abstand) gilt statt der Rate das Minutenbudget: Restminuten = min(Rate, max(mu0 * F - gespielte Minuten, BLOWOUT_FLOOR * Rate)); sonst Rate * min(F, 1,1).
   - Fouls: FOUL_FACTORS (Foulprobleme); 6 Fouls = ausgeschieden = 0 Minuten.
   - Verdacht auf Ausfall im Spiel (siehe unten) = Faktor OUT_FACTOR.
3. Punkte je Minute: Vorab-Wert aus der Prognose (Teamabgleich), mit den bisherigen Punkten und Minuten zu einem Schaetzer gemischt (Bayes: (Punkte + K * ppm_vorab) / (Minuten + K), K = PRIOR_MINUTES).
4. Punkte in der Restzeit: negative Binomialverteilung mit Erwartung lambda = ppm * Restminuten und Varianz VAR_FACTOR * lambda + (ppm * RESTMIN_SD_SHARE * Restminuten)^2 (Treffer kommen gebuendelt,
   die Restminuten sind unsicher). Chance = P(Rest >= N - bisherige Punkte); Punkte >= N = 1, keine Restminuten = 0.
Ausfall im Spiel (soweit der Boxscore es hergibt): 6 Fouls (ausgeschieden), Boxscore-Status inaktiv ohne Einsatz, oder ein Stammspieler (Vorab-Rolle "Stamm") ist seit mindestens OUT_IDLE_SECONDS Spielzeit
nicht mehr auf dem Feld (idle_s aus dem Live-Feed) bei mindestens OUT_MIN_PLAYED Minuten Einsatz: Verdacht auf Verletzung/Sperre, Chance deutlich gesenkt, mit Hinweis.
Ohne Prognose-Snapshot (pre=None): allgemeine Annahmen (DEFAULT_MU0, Liga-Punkte je Minute) mit Hinweis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.stats import nbinom, poisson

from engine import game_clock as gc
from engine import player_forecast as pf

LIVE_VERSION = "live-1"
STATUS = "UNGEPRÜFT"
LIVE_CONSTANTS = {
    "version": LIVE_VERSION,
    "blowout_min_factor": 0.97,        # darunter: Minutenbudget statt Rate
    "blowout_floor": 0.25,             # mindestens so viel der Rate bleibt auch im Blowout (Garbage Time)
    "blowout_max_boost": 1.10,         # enge Spiele: hoechstens +10 % Restminuten
    "foul_factors": {                  # (Fouls, Viertel <= 3) -> Faktor auf die Restminuten; (Fouls, Viertel >= 4)
        3: (0.90, 1.00), 4: (0.70, 0.85), 5: (0.50, 0.60),
    },
    "foul_out": 6,
    "prior_minutes": 12.0,             # Gewicht des Vorab-Werts (Punkte je Minute) in Minuten
    "var_factor": 2.0,                 # Varianz/Erwartung der Punkte in der Restzeit (gebuendelte Treffer)
    "restmin_sd_share": 0.25,          # Unsicherheit der Restminuten (Anteil)
    "out_idle_seconds": 720.0,         # Stammspieler so lange (Spielzeit) nicht auf dem Feld: Verdacht auf Ausfall
    "out_min_played": 1.0,             # ... wenn er vorher mindestens so viele Minuten gespielt hat
    "out_factor": 0.10,                # Faktor auf die Restminuten bei Verdacht
    "default_mu0": 26.0,               # ohne Prognose-Snapshot
    "default_ppm": 0.49,               # Liga-Durchschnitt Punkte je Minute (2025-26)
    "ot_seconds": 300.0,
}
C = LIVE_CONSTANTS


@dataclass(frozen=True)
class LiveChance:
    probability: float                 # Chance auf mindestens N Punkte (0..1)
    remaining_minutes: float           # erwartete Restminuten des Spielers
    expected_remaining_points: float
    notes: tuple = ()                  # Hinweise (Foulprobleme, Blowout, Ausfall, fehlende Prognose)
    out: bool = False                  # ausgeschieden / inaktiv / Verdacht auf Ausfall
    version: str = LIVE_VERSION
    status: str = STATUS


def remaining_game_seconds(clock: gc.GameClock, margin: int) -> float:
    """Restzeit des Spiels in Sekunden (siehe Methode, Punkt 1)."""
    if clock.is_final:
        return 0.0
    if clock.period <= gc.REG_PERIODS:
        rest = (gc.REG_PERIODS - clock.period) * gc.QUARTER_SECONDS + max(0.0, clock.seconds_left)
        if rest <= 0 and margin == 0:
            return C["ot_seconds"]                                      # Gleichstand nach 4 Vierteln: Verlaengerung
        return float(rest)
    left = max(0.0, float(clock.seconds_left))                          # Verlaengerung: Rest der laufenden; am Ende der Verlaengerung bei Gleichstand eine weitere
    return left if left > 0 else (C["ot_seconds"] if margin == 0 else 0.0)


def foul_factor(fouls: int, period: int) -> float:
    if fouls >= C["foul_out"]:
        return 0.0
    pair = C["foul_factors"].get(int(fouls))
    if not pair:
        return 1.0
    return pair[0] if period <= 3 else pair[1]


def points_distribution_tail(lam: float, var: float, k: int) -> float:
    """P(Rest >= k) fuer eine negative Binomialverteilung mit Erwartung lam und Varianz var (var > lam, sonst Poisson)."""
    if k <= 0:
        return 1.0
    if lam <= 1e-9:
        return 0.0
    if var <= lam * 1.0001:
        return float(poisson.sf(k - 1, lam))
    n = lam * lam / (var - lam)
    p = lam / var
    return float(nbinom.sf(k - 1, n, p))


def live_chance(milestone: int, player, clock: gc.GameClock, home_score: int, away_score: int, pre: dict | None = None) -> LiveChance:
    """Live-Chance, dass der Spieler mindestens `milestone` Punkte erreicht. player: PlayerLive (points, minutes, fouls, status, idle_s ...), clock: GameClock des Spiels,
    pre: Spieler aus dem Prognose-Snapshot (minutes{base, mean, role}, expected_points_raw; Rückfall: minutes_adjusted, expected_points_adjusted) oder None."""
    notes = []
    pts, played, fouls = int(player.points), float(player.minutes), int(player.fouls)
    need = int(milestone) - pts
    if need <= 0:
        return LiveChance(1.0, 0.0, 0.0, ())
    margin = int(home_score) - int(away_score)
    R = remaining_game_seconds(clock, margin)
    if R <= 0:
        return LiveChance(0.0, 0.0, 0.0, ("Spiel vorbei",), False)
    # Vorab-Werte
    if pre and pre.get("ok", True) and pre.get("minutes"):
        mu0 = float(pre["minutes"].get("base") or pre["minutes"].get("mean") or C["default_mu0"])
        # Start mit den Roh-Werten (Modell A: erwartete Punkte roh / Minuten roh); der Teamabgleich (Modell B) ist ausgeblendet. mu0 = minutes.base ist bereits roh.
        if pre.get("expected_points_raw") is not None and pre["minutes"].get("mean"):
            m_raw = float(pre["minutes"]["mean"])
            ppm_pre = float(pre["expected_points_raw"]) / m_raw if m_raw > 0 else C["default_ppm"]
        else:   # alter Snapshot ohne Roh-Werte: bisherige (Teamabgleich-)Werte, sichtbar im Hinweis
            m_adj = float(pre.get("minutes_adjusted") or pre["minutes"].get("mean") or mu0)
            ppm_pre = float(pre.get("expected_points_adjusted") or 0.0) / m_adj if m_adj > 0 else C["default_ppm"]
            notes.append("Snapshot ohne Roh-Werte: Live-Start mit Teamabgleich-Werten (Rückfall)")
        role = pre["minutes"].get("role") or pf.role_for_minutes(mu0)
    else:
        mu0, ppm_pre, role = C["default_mu0"], C["default_ppm"], pf.role_for_minutes(C["default_mu0"])
        notes.append("ohne Prognose-Snapshot: allgemeine Annahmen (26 Minuten, Liga-Durchschnitt)")
    # Ausfall im Spiel
    out = False
    status = getattr(player, "status", "")
    idle = float(getattr(player, "idle_s", 0.0) or 0.0)
    if fouls >= C["foul_out"]:
        out = True
        notes.append("ausgeschieden (6 Fouls)")
        return LiveChance(0.0, 0.0, 0.0, tuple(notes), True)
    if status == "nicht gespielt" and played <= 0:
        notes.append("laut Boxscore inaktiv / nicht im Einsatz")
        return LiveChance(0.0, 0.0, 0.0, tuple(notes), True)
    out_factor = 1.0
    if role == "Stamm" and played >= C["out_min_played"] and status != "spielt" and idle >= C["out_idle_seconds"]:
        out, out_factor = True, C["out_factor"]
        notes.append(f"seit {int(idle) // 60} Min. Spielzeit nicht mehr auf dem Feld: Verdacht auf Verletzung oder Sperre")
    # Restminuten
    period = max(1, clock.period)
    rate_rem = (mu0 / 48.0) * (R / 60.0)
    F = pf.blowout_factor_live(mu0, abs(margin), R)
    if F >= C["blowout_min_factor"]:
        rem = rate_rem * min(F, C["blowout_max_boost"])
    else:
        budget = mu0 * F - played
        rem = min(rate_rem, max(budget, C["blowout_floor"] * rate_rem))
        notes.append(f"Blowout-Abschlag (Abstand {abs(margin)} Punkte, Faktor {F:.2f})")
    ff = foul_factor(fouls, period)
    if ff < 1.0:
        notes.append(f"Foulprobleme ({fouls} Fouls, Faktor {ff:.2f})")
    rem = max(0.0, rem * ff * out_factor)
    # Punkte je Minute und Verteilung
    K = C["prior_minutes"]
    ppm = (pts + K * ppm_pre) / (played + K)
    lam = ppm * rem
    var = C["var_factor"] * lam + (ppm * C["restmin_sd_share"] * rem) ** 2
    p = points_distribution_tail(lam, var, need)
    return LiveChance(max(0.0, min(1.0, p)), rem, lam, tuple(notes), out)

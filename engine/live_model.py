"""
Live-Modell (Baustein 2): reine Formeln, ohne Streamlit, ohne I/O. Eingabe: Anker (Vorab-Prognose aus dem Schnappschuss), Spielzustand (game_clock),
aktueller Stand, optional Ballbesitze. Ausgabe: erwartete Endstaende, Streuungen und Wahrscheinlichkeiten je Markt (Sieger, Spread, Total, Team Total).

Formeln (t = gespielte reguläre Sekunden, Anteile aus config.settings, kalibriert mit analysis/live_calibration.py):
  Tempo:        pace_live = Besitze je Team * 48 / gespielte Minuten;  w = n / (n + K);  pace_est = w * pace_live + (1 - w) * P0;
                pace_mult = pace_est / P0 (begrenzt auf LIVE_PACE_MULT_CLIP).  Ohne Besitze: pace_mult = 1.
  Erwartung:    Endstand = Stand + Vorab * (1 - Anteil(t)) * pace_mult * Faktoren + Verlaengerungs-Korrektur
  Streuung:     sigma = Vorab-Sigma * wurzel(Rest-Varianzanteil(t) + Verlaengerungs-Korrektur)
  Wahrscheinl.: Normalverteilung N(Endstand, sigma) fuer Total, Team Total und Spread; Sieger ueber die regulaere Marge (diskret) plus Gleichstand * p_ot.
  Verlaengerung: Die Vorab-Werte gelten inklusive Verlaengerung (Historie). Live zaehlt nur die AENDERUNG der Gleichstands-Wahrscheinlichkeit gegen den Anpfiff:
                Mittel = Stand + Vorab * Rest + mu_OT * (p_gleich_jetzt - p_gleich_anpfiff * Rest). Beim Anpfiff ist der Zusatz null, nach einem Gleichstand
                am Ende von Q4 kommt eine ganze Verlaengerung dazu (mu_OT = Vorab * 5/48 * 0,93). In der Verlaengerung rechnet dieselbe Formel mit 5 Minuten.
  Sieger:       sigmas_version "2" (ab 23.10.2026): Die Vorab-Siegchance ist selbst die Normalverteilung um den Spread (engine.line_probabilities.win_prob_home). Live gilt dieselbe
                Verteilung: P(Sieger Heim) = P(Marge am Ende > 0) = p_spread("home", 0), beim Anpfiff exakt gleich home_win_prob (Abweichung nur durch dessen Rundung auf 4 Stellen).
                Aeltere Schnappschuesse (Version 1, Elo-Logistik): Die Normalverteilung liefert nicht exakt die kalibrierte Vorab-Wahrscheinlichkeit; deshalb wird einmal je Spiel
                eine "effektive Marge" bestimmt, bei der die Formel (diskret, mit Gleichstand * Verlaengerungs-Sieger) beim Anpfiff genau home_win_prob ergibt (Bisektion).
  Anpfiff:      Mit Stand 0:0, t = 0, pace_mult = 1 und Faktoren 1,0 sind alle Werte gleich den Vorab-Funktionen (engine/line_probabilities.prob_above, spread_rows).
Faktoren fuer Fouls/Bonus, Blowout und Ausfall eines Stars sind in Version 1 NEUTRAL (1,0) und werden mitgeschrieben (LiveProjection.factors).
Spielende (FINAL): alle Wahrscheinlichkeiten ergeben sich aus dem tatsaechlichen Ergebnis (0 oder 1). Ganzzahlige Linien: Gleichstand mit der Linie zaehlt als NICHT gewonnen (keine Rueckzahlung modelliert).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

from config.settings import (
    LIVE_OT_MINUTES, LIVE_OT_SCORING_FACTOR, LIVE_PACE_K, LIVE_PACE_MULT_CLIP, LIVE_PACE_P0,
    LIVE_SHARE_MARGIN, LIVE_SHARE_POINTS, LIVE_VAR_REST_MARGIN, LIVE_VAR_REST_TEAM, LIVE_VAR_REST_TOTAL,
)
from engine import game_clock as gc
from engine.line_probabilities import SPREAD_SIGMA, TEAM_TOTAL_SIGMA, TOTAL_SIGMA

FORMULA_VERSION = "live-1"
_ND = NormalDist()
OT_SHARE = LIVE_OT_MINUTES / 48.0            # Laenge einer Verlaengerung im Verhaeltnis zum Spiel
_EPS = 1e-9


# ----------------------------------------------------------------------------------------------- Eingaben
@dataclass(frozen=True)
class Anchor:
    """Vorab-Prognose (Modell-Schnappschuss beim Anpfiff). Gleiche Felder und Bedeutung wie projection_snapshots[...]['projection']."""
    exp_total: float
    exp_spread: float                 # positiv = Heim staerker
    home_score: float
    away_score: float
    home_win_prob: float
    pace: float | None = None         # erwartete Besitze je Team und 48 Min. (None = Liga-P0)
    sigma_spread: float = SPREAD_SIGMA
    sigma_total: float = TOTAL_SIGMA
    sigma_team: float = TEAM_TOTAL_SIGMA
    source: str = "schnappschuss"     # "schnappschuss" | "live_nachgerechnet" (Anker fehlt im Schnappschuss und wurde spaeter berechnet)
    sigmas_version: str = "1"         # "2": home_win_prob = Normalverteilung um exp_spread mit sigma_spread (Siegchance und Spread aus derselben Verteilung); "1": Elo-Logistik

    @classmethod
    def from_snapshot(cls, version: dict, source: str = "schnappschuss") -> "Anchor":
        p, s = version["projection"], version.get("sigmas") or {}
        return cls(float(p["exp_total"]), float(p["exp_spread"]), float(p["home_score"]), float(p["away_score"]), float(p["home_win_prob"]),
                   sigma_spread=float(s.get("spread", SPREAD_SIGMA)), sigma_total=float(s.get("total", TOTAL_SIGMA)),
                   sigma_team=float(s.get("team_total", TEAM_TOTAL_SIGMA)), source=source, sigmas_version=str(version.get("sigmas_version") or "1"))


@dataclass(frozen=True)
class Possessions:
    """Bisherige Ballbesitze beider Teams (aus dem Boxscore: FGA + 0,44 FTA - OREB + TOV)."""
    home: float
    away: float


@dataclass(frozen=True)
class Factors:
    """Multiplikatoren auf die erwarteten Restpunkte. Version 1: alle 1,0 (nicht belegt); werden in jeder Zeile mitgeschrieben, damit sie spaeter aus den Aufzeichnungen kalibriert werden koennen."""
    foul_bonus: float = 1.0
    blowout: float = 1.0
    star_out: float = 1.0

    @property
    def product(self) -> float:
        return self.foul_bonus * self.blowout * self.star_out


def possessions_from_stats(stats: dict) -> float:
    """Ballbesitze eines Teams aus den Boxscore-Teamwerten (statistics)."""
    return (float(stats.get("fieldGoalsAttempted") or 0) + 0.44 * float(stats.get("freeThrowsAttempted") or 0)
            - float(stats.get("reboundsOffensive") or 0) + float(stats.get("turnoversTotal", stats.get("turnovers")) or 0))


# ----------------------------------------------------------------------------------------------- Bausteine
def interp(table, t: float) -> float:
    """Wert einer Viertel-Tabelle (5 Stuetzstellen: Anpfiff, Ende Q1..Q4) zur Zeit t (Sekunden, regulaer), linear innerhalb eines Viertels."""
    t = min(max(float(t), 0.0), float(gc.REG_SECONDS))
    i = min(int(t // gc.QUARTER_SECONDS), 3)
    frac = (t - i * gc.QUARTER_SECONDS) / gc.QUARTER_SECONDS
    return table[i] + (table[i + 1] - table[i]) * frac


def tie_mass(mean: float, sigma: float) -> float:
    """Wahrscheinlichkeit einer ganzzahligen Marge 0 bei N(mean, sigma) (Stetigkeitskorrektur +-0,5). sigma ~ 0: exakt 1 oder 0."""
    if sigma < _EPS:
        return 1.0 if abs(mean) < 0.5 else 0.0
    return _ND.cdf((0.5 - mean) / sigma) - _ND.cdf((-0.5 - mean) / sigma)


def p_ot_home(eff_margin: float, sigma_margin: float) -> float:
    """Sieger einer Verlaengerung: Marge ~ N(m * 5/48, sigma * wurzel(5/48)) -> P = Phi(m / sigma * wurzel(5/48)), nahezu offen mit kleinem Heimvorteil."""
    return _ND.cdf(eff_margin / sigma_margin * math.sqrt(OT_SHARE))


def winner_prob_home(mean_margin: float, sigma: float, p_ot: float) -> float:
    """P(Heim gewinnt) bei regulaerer Marge ~ N(mean, sigma) (ganzzahlig) und Verlaengerungs-Sieger p_ot im Gleichstand."""
    if sigma < _EPS:
        return 1.0 if mean_margin > 0.5 else 0.0 if mean_margin < -0.5 else p_ot
    pos = 1.0 - _ND.cdf((0.5 - mean_margin) / sigma)
    return pos + tie_mass(mean_margin, sigma) * p_ot


def effective_margin(home_win_prob: float, sigma_margin: float) -> float:
    """Marge m, bei der winner_prob_home(m, sigma, p_ot_home(m, sigma)) beim Anpfiff genau home_win_prob ergibt (Bisektion, 60 Schritte = Genauigkeit 1e-16, monoton)."""
    p = min(max(float(home_win_prob), 1e-6), 1 - 1e-6)
    lo, hi = -80.0, 80.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if winner_prob_home(mid, sigma_margin, p_ot_home(mid, sigma_margin)) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pace_multiplier(poss: Possessions | None, elapsed_total_s: float, anchor_pace: float | None = None) -> tuple[float, float | None, float, float]:
    """(pace_mult, pace_live, weight, pace_est). Ohne Besitze oder in den ersten Sekunden: 1,0."""
    p0 = float(anchor_pace or LIVE_PACE_P0)
    if poss is None or elapsed_total_s < 60:
        return 1.0, None, 0.0, p0
    n = (poss.home + poss.away) / 2.0
    live = n * 48.0 / (elapsed_total_s / 60.0)
    w = n / (n + LIVE_PACE_K)
    est = w * live + (1 - w) * p0
    lo, hi = LIVE_PACE_MULT_CLIP
    return min(max(est / p0, lo), hi), live, w, est


# ----------------------------------------------------------------------------------------------- Ergebnis
@dataclass(frozen=True)
class LiveProjection:
    formula_version: str
    anchor_source: str
    phase: str
    final: bool
    home_pts: int
    away_pts: int
    expected_total: float
    expected_home: float
    expected_away: float
    expected_margin: float
    sd_total: float
    sd_home: float
    sd_away: float
    sd_margin: float
    p_tie: float                      # Gleichstand am Ende der regulaeren Zeit (bzw. der laufenden Verlaengerung)
    p_tie_anchor: float
    p_ot_home: float
    eff_margin: float                 # fuer den Sieger-Markt
    sd_reg_margin: float
    mean_reg_margin: float
    pace_mult: float
    pace_live: float | None
    pace_weight: float
    factors: dict = field(default_factory=dict)
    sigmas_version: str = "1"
    winner_mode: str = "effektive_marge"   # "gleiche_verteilung" (sigmas_version 2) | "effektive_marge" (aeltere Schnappschuesse mit Logistik-Siegchance)

    # --- Maerkte
    def p_over_total(self, line: float) -> float:
        if self.final or self.home_pts + self.away_pts > line:
            return 1.0 if self.home_pts + self.away_pts > line else 0.0
        return _over(self.expected_total, line, self.sd_total)

    def p_over_team(self, side: str, line: float) -> float:
        pts = self.home_pts if side == "home" else self.away_pts
        if self.final or pts > line:
            return 1.0 if pts > line else 0.0
        mean, sd = (self.expected_home, self.sd_home) if side == "home" else (self.expected_away, self.sd_away)
        return _over(mean, line, sd)

    def p_spread(self, side: str, line: float) -> float:
        """Wette auf 'side' mit Linie line aus Sicht dieser Mannschaft (Heim -4,5: Heim gewinnt mit mehr als 4,5). Gewonnen, wenn Marge_side + line > 0."""
        if self.final:
            d = (self.home_pts - self.away_pts) * (1 if side == "home" else -1)
            return 1.0 if d + line > 0 else 0.0
        if side == "home":
            return _over(self.expected_margin, -line, self.sd_margin)
        return 1.0 - _over(self.expected_margin, line, self.sd_margin)

    def p_winner(self, side: str) -> float:
        if self.final:
            return 1.0 if (self.home_pts > self.away_pts) == (side == "home") else 0.0
        if self.winner_mode == "gleiche_verteilung":       # P(Marge am Ende > 0) aus derselben Verteilung wie der Spread bei Linie 0
            p = _over(self.expected_margin, 0.0, self.sd_margin)
        else:
            p = winner_prob_home(self.mean_reg_margin, self.sd_reg_margin, self.p_ot_home)
        return p if side == "home" else 1.0 - p

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["factors"] = dict(self.factors)
        return d


def _over(mean: float, line: float, sigma: float) -> float:
    """Wie engine.line_probabilities.prob_above: P(X > line) fuer X ~ N(mean, sigma)."""
    if sigma < _EPS:
        return 1.0 if mean > line else 0.0
    return 1.0 - _ND.cdf((line - mean) / sigma)


# ----------------------------------------------------------------------------------------------- Hauptfunktion
def project(anchor: Anchor, clock: gc.GameClock, home_pts: int, away_pts: int, poss: Possessions | None = None, factors: Factors | None = None) -> LiveProjection:
    factors = factors or Factors()
    H, A = int(home_pts), int(away_pts)
    d, cur = H - A, H + A
    mu_t, mu_m, mu_h, mu_a = anchor.exp_total, anchor.exp_spread, anchor.home_score, anchor.away_score
    s_t, s_m, s_h, s_a = anchor.sigma_total, anchor.sigma_spread, anchor.sigma_team, anchor.sigma_team
    same_dist = anchor.sigmas_version != "1"                       # Siegchance aus derselben Normalverteilung wie der Spread (Version 2)
    eff = mu_m if same_dist else effective_margin(anchor.home_win_prob, s_m)
    pot = p_ot_home(eff, s_m)
    mode = "gleiche_verteilung" if same_dist else "effektive_marge"
    p0 = tie_mass(mu_m, s_m)                                       # Gleichstand beim Anpfiff (Normalverteilung, gleiche Formel wie live)
    ot = OT_SHARE * LIVE_OT_SCORING_FACTOR
    mult, pace_live, w, _ = pace_multiplier(poss, clock.elapsed_total_s, anchor.pace)
    f = factors.product
    fd = {"foul_bonus": factors.foul_bonus, "blowout": factors.blowout, "star_out": factors.star_out}

    if clock.is_final:
        return LiveProjection(FORMULA_VERSION, anchor.source, clock.phase, True, H, A, float(cur), float(H), float(A), float(d), 0.0, 0.0, 0.0, 0.0,
                              0.0, p0, pot, eff, 0.0, float(d), mult, pace_live, w, fd, anchor.sigmas_version, mode)

    if clock.ot_number == 0:
        t = clock.elapsed_regulation_s
        rp, rm = 1.0 - interp(LIVE_SHARE_POINTS, t), 1.0 - interp(LIVE_SHARE_MARGIN, t)
        vt, vm, vh = (interp(LIVE_VAR_REST_TOTAL, t), interp(LIVE_VAR_REST_MARGIN, t), interp(LIVE_VAR_REST_TEAM, t))
        m_reg = d + mu_m * rm * mult                                # regulaere Marge am Ende (Mittel)
        sd_reg = s_m * math.sqrt(vm)
        p_now = tie_mass(m_reg, sd_reg)
        # Mittel: Vorab * Rest - Anker-Gleichstand * OT * Rest + jetziger Gleichstand * OT (so wird beim Anpfiff exakt das Vorab-Mittel erreicht)
        e_total = cur + mu_t * rp * mult * f + mu_t * ot * (p_now - p0 * rp * mult * f)
        e_home = H + mu_h * rp * mult * f + mu_h * ot * (p_now - p0 * rp * mult * f)
        e_away = A + mu_a * rp * mult * f + mu_a * ot * (p_now - p0 * rp * mult * f)
        e_margin = m_reg + mu_m * ot * (p_now - p0 * rm * mult)
        k = OT_SHARE
        sd_total = s_t * math.sqrt(max(0.0, 1.0 + (vt - 1.0) * (1 - p0 * k) + (p_now - p0) * k))
        sd_home = s_h * math.sqrt(max(0.0, 1.0 + (vh - 1.0) * (1 - p0 * k) + (p_now - p0) * k))
        sd_away = s_a * math.sqrt(max(0.0, 1.0 + (vh - 1.0) * (1 - p0 * k) + (p_now - p0) * k))
        sd_margin = s_m * math.sqrt(max(0.0, 1.0 + (vm - 1.0) * (1 - p0 * k) + (p_now - p0) * k))
        mean_reg = d + eff * rm * mult
        sd_reg_w = sd_reg
    else:                                                           # Verlaengerung: nur die Rest-Zeit der laufenden Verlaengerung, danach ggf. eine weitere
        left = min(max((clock.seconds_left or 0.0) / (gc.OT_SECONDS), 0.0), 1.0)
        m_ot = d + mu_m * ot * left * mult
        sd_ot = s_m * math.sqrt(OT_SHARE * left)
        p_now = tie_mass(m_ot, sd_ot)
        e_total = cur + mu_t * ot * left * mult * f + mu_t * ot * p_now
        e_home = H + mu_h * ot * left * mult * f + mu_h * ot * p_now
        e_away = A + mu_a * ot * left * mult * f + mu_a * ot * p_now
        e_margin = m_ot + mu_m * ot * p_now
        var_unit = OT_SHARE * (left + p_now)
        sd_total, sd_home, sd_away, sd_margin = (s * math.sqrt(var_unit) for s in (s_t, s_h, s_a, s_m))
        mean_reg = d + eff * ot * left
        sd_reg_w = sd_ot

    return LiveProjection(FORMULA_VERSION, anchor.source, clock.phase, False, H, A, e_total, e_home, e_away, e_margin, sd_total, sd_home, sd_away, sd_margin,
                          p_now, p0, pot, eff, sd_reg_w, mean_reg, mult, pace_live, w, fd, anchor.sigmas_version, mode)

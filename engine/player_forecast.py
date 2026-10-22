"""
Spieler-Tab, Bausteine P5+P6: Prognose fuer Spieler-PUNKTE (erwartete Minuten, erwartete Punkte, Chance P(Punkte >= N) je Meilenstein). Reine Logik, kein Netz, schreibt nichts.
Liest nur: data/player_history.py (Spielverlauf), data/projection_snapshots.py (Spread/Total des Spielmodells).

UNGEPRUEFT: die Methode ist noch nicht gegen Ergebnisse backgetestet (nur grobe Pruefung, analysis/player_forecast_quickcheck.py). Nicht als Wettempfehlung lesen.

Methode
1. Gewichte: Spiele vor dem Stichtag, beide Saisons verbunden, neueste zuerst. Innerhalb einer Saison fallen die Gewichte exponentiell (Halbwertszeit HALF_LIFE_GAMES = 8 Spiele).
   Schrumpfung nach Spielzahl: Anteil der laufenden Saison = n / (n + PRIOR_GAMES_K), der Rest gehoert der Vorsaison (n = Spiele des Spielers in der laufenden Saison;
   0 Spiele -> nur Vorsaison, 8 Spiele -> je 50 %, 24 Spiele -> 75 %).
2. Minuten: gewichteter Mittelwert (Basis) und gewichtete Standardabweichung (zu MINUTES_SD_PRIOR geschrumpft, wenn die wirksame Stichprobe klein ist).
3. Blowout-Abschlag: Stammspieler und Rotationsspieler verlieren Minuten, wenn der Endabstand gross wird. Die Faktoren BLOWOUT_CURVE sind aus 2025-26 gemessen
   (26 651 Spielerzeilen, Verhaeltnis Minuten / Saisonmittel des Spielers, nach |Endabstand des Teams| gruppiert). Erwartungsfaktor = E[f(|M|)] mit M ~ Normal(erwarteter Spread
   aus Sicht des Teams, SPREAD_SIGMA 13,2) geteilt durch E[f(|M|)] ueber den typischen Abstand (Normal(0, BLOWOUT_REF_SIGMA)), weil die Basis-Minuten diese Mischung schon enthalten.
   Fehlt der Schnappschuss: Spread 0 und eine Warnung.
4. Punkte je Minute (ppm): je Spiel Punkte / Minuten (nur Spiele mit mindestens MIN_PPM_MINUTES Minuten), gleich gewichtet wie die Minuten (inkl. Schrumpfung zur Vorsaison).
5. Verteilung: gewichtete empirische Verteilung der ppm der letzten Spiele, hochgerechnet auf die prognostizierten Minuten, die selbst als Normalverteilung (Mittel nach Blowout,
   Streuung aus der Historie, auf 0..48 begrenzt) in MINUTE_POINTS Quantilen eingehen. Jede Kombination (Spiel, Minutenquantil) ergibt einen Punktewert x; eine leichte Glaettung
   (Normalkern, Breite 1 + 0,05 x) macht daraus P(Punkte >= N) = 1 - Phi((N - 0,5 - x) / h). Gruende: keine feste Verteilungsannahme fuer die Treffer (Spieler streuen unterschiedlich), die
   Minutenstreuung wird nicht doppelt gezaehlt (ppm ist je Spiel schon durch die Minuten geteilt), und die Summe monotoner Kurven ist selbst nicht steigend in N und liegt in 0..1.

NICHT enthalten (bekannte Einschraenkungen dieser Version)
- Ausfaelle von Mitspielern (mehr Minuten und Wuerfe bei Ausfall eines Stars) und Rueckkehr von Verletzten.
- Gegner-Verteidigung und Tempo (kein Einfluss auf Punkte je Minute).
- Ob ein Spieler ueberhaupt spielt (Einsatzwahrscheinlichkeit, Schonung, Verletzung): die Prognose gilt "wenn er spielt".
- Heim/Gast-Effekt, Ruhetage, Foul-Probleme, Overtime.
Der Spielgesamt-Total (exp_total) wird mitgefuehrt, aber nicht verwendet.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import ndtr, ndtri

from data import player_history as ph
from data import projection_snapshots as snaps
from engine.line_probabilities import SPREAD_SIGMA

UNVERIFIED = "UNGEPRÜFT"
UNVERIFIED_TEXT = "UNGEPRÜFT: Modell noch nicht gegen Ergebnisse geprüft (kein Backtest). Gilt für den Fall, dass der Spieler spielt."

HALF_LIFE_GAMES = 8
PRIOR_GAMES_K = 8
MIN_PPM_MINUTES = 8.0
MINUTES_SD_PRIOR, MINUTES_SD_PRIOR_WEIGHT = 5.0, 4.0
MINUTES_SD_FLOOR = 2.0
MINUTE_POINTS = 9
MAX_MINUTES = 48.0
MAX_N = 60
FEW_GAMES = 10                    # unter so vielen Spielen insgesamt: Hinweis "wenige Spiele"
ROLE_CHANGE_MINUTES = 5.0         # Minuten der letzten 5 weichen so weit vom gewichteten Mittel ab: Hinweis "Rollenwechsel"
ROLE_STARTER_MIN, ROLE_ROTATION_MIN = 28.0, 20.0

# Blowout-Kurve: Verhaeltnis Minuten / Saisonmittel des Spielers nach |Endabstand|, gemessen auf 2025-26 (Regular Season, 22 886 Zeilen von Spielern mit mindestens 20 Spielen;
# Abstand = Team-Endabstand aus der Summe der Spielerpunkte). Stuetzstellen = Mitten der Abstandsgruppen 0-3, 3-6, 6-9, 9-12, 12-15, 15-18, 18-21, 21-25, 25-30, ab 30.
BLOWOUT_X = (1.5, 4.5, 7.5, 10.5, 13.5, 16.5, 19.5, 23.0, 27.5, 35.0)
BLOWOUT_CURVE = {
    # Stammspieler (Saisonmittel > 28 Min., n = 7 196): knapp 8 % mehr Minuten in engen Spielen, 15 % weniger bei 30+ Punkten Abstand
    "Stamm": (1.077, 1.059, 1.054, 1.032, 1.003, 0.979, 0.940, 0.916, 0.886, 0.845),
    # Rotation (20 bis 28 Min., n = 8 854): halb so stark: von 1,04 auf 0,94
    "Rotation": (1.006, 1.028, 1.037, 1.025, 0.996, 0.995, 0.971, 0.976, 0.958, 0.938),
}
# Bank (unter 20 Min., n = 6 836): Messwerte zwischen 0,975 und 1,031 ohne erkennbaren Verlauf -> kein Abschlag (Faktor 1,0).
BLOWOUT_REF_SIGMA = 17.2          # Streuung des Endabstands ueber alle Spiele 2025-26 (Standardabweichung der Team-Endabstaende), Referenz fuer den "typischen" Abstand
_GRID = np.linspace(-80.0, 80.0, 641)


# ----------------------------------------------------------------------------- Gewichte, Minuten
def role_for_minutes(minutes: float) -> str:
    return "Stamm" if minutes > ROLE_STARTER_MIN else "Rotation" if minutes > ROLE_ROTATION_MIN else "Bank"


def game_weights(games: list[dict], season: str) -> list[float]:
    """Gewichte (Summe 1) fuer Spiele, neueste zuerst. Innerhalb der laufenden Saison und der Vorsaison exponentiell fallend; Anteil der laufenden Saison n / (n + K)."""
    cur = [i for i, g in enumerate(games) if g["season"] == season]
    prev = [i for i, g in enumerate(games) if g["season"] != season]
    if not games:
        return []
    if not prev:
        share_cur = 1.0
    elif not cur:
        share_cur = 0.0
    else:
        share_cur = len(cur) / (len(cur) + PRIOR_GAMES_K)
    out = [0.0] * len(games)
    for idx, share in ((cur, share_cur), (prev, 1.0 - share_cur)):
        raw = [0.5 ** (k / HALF_LIFE_GAMES) for k in range(len(idx))]
        total = sum(raw) or 1.0
        for i, r in zip(idx, raw):
            out[i] = share * r / total
    return out


def weighted_mean_sd(values: list[float], weights: list[float]) -> tuple[float, float]:
    """Gewichteter Mittelwert und Standardabweichung (Gewichte duerfen unnormiert sein). Die Streuung wird bei kleiner wirksamer Stichprobe zu MINUTES_SD_PRIOR geschrumpft."""
    total = sum(weights)
    mean = sum(v * w for v, w in zip(values, weights)) / total
    var = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / total
    n_eff = total ** 2 / sum(w * w for w in weights)
    sd = math.sqrt((n_eff * var + MINUTES_SD_PRIOR_WEIGHT * MINUTES_SD_PRIOR ** 2) / (n_eff + MINUTES_SD_PRIOR_WEIGHT))
    return mean, max(MINUTES_SD_FLOOR, sd)


# ----------------------------------------------------------------------------- Blowout
def _expected_factor(role: str, mean_margin: float, sigma: float) -> float:
    f = np.interp(np.abs(_GRID), BLOWOUT_X, BLOWOUT_CURVE[role])
    p = np.exp(-0.5 * ((_GRID - mean_margin) / sigma) ** 2)
    return float((f * p).sum() / p.sum())


_REF = {role: _expected_factor(role, 0.0, BLOWOUT_REF_SIGMA) for role in BLOWOUT_CURVE}


def blowout_factor(base_minutes: float, team_spread: float = 0.0) -> float:
    """Erwartungsfaktor auf die Minuten. team_spread = erwarteter Endabstand aus Sicht des Teams (positiv = Team staerker). Bank: 1,0."""
    role = role_for_minutes(base_minutes)
    if role not in BLOWOUT_CURVE:
        return 1.0
    return _expected_factor(role, float(team_spread), SPREAD_SIGMA) / _REF[role]


# ----------------------------------------------------------------------------- Kontext aus dem Schnappschuss
def context_for_game(game_key: str) -> dict:
    """Spread/Total des Spielmodells aus dem letzten Schnappschuss des Spiels (nur lesen). {'found', 'exp_spread' (positiv = Heim staerker), 'exp_total', 'home', 'away'}."""
    g = (snaps.load().get("games") or {}).get(game_key)
    try:
        proj = g["versions"][-1]["projection"]
        return {"found": True, "exp_spread": float(proj["exp_spread"]), "exp_total": float(proj["exp_total"]), "home": g.get("home"), "away": g.get("away")}
    except (TypeError, KeyError, IndexError, ValueError):
        return {"found": False, "exp_spread": None, "exp_total": None, "home": (g or {}).get("home"), "away": (g or {}).get("away")}


# ----------------------------------------------------------------------------- Prognose
def forecast_player(person_id: int, before_date, home: bool | None = None, exp_spread: float | None = None, exp_total: float | None = None,
                    games: list[dict] | None = None, name: str | None = None) -> dict:
    """Prognose fuer ein Spiel am Tag before_date (nur Spiele DAVOR zaehlen). home: Team des Spielers ist Heimteam; exp_spread: erwarteter Spread des Spielmodells
    (positiv = Heim staerker). games: schon gefilterte Spiele (neueste zuerst) statt Zugriff auf den Verlauf (fuer Pruefungen). Wirft nie wegen fehlender Daten."""
    day = str(before_date)[:10]
    season = ph.season_of_date(day)
    warnings: list[str] = []
    if games is None:
        games = ph.get_player_games(person_id, before_date=day)
    else:
        games = [g for g in games if g["date"] < day]
        games.sort(key=lambda g: (g["date"], g["game_id"]), reverse=True)
    base = {"person_id": int(person_id), "name": name or (games[0]["name"] if games else None), "before_date": day, "status": UNVERIFIED}
    if not games:
        return {**base, "ok": False, "reason": "kein Verlauf (keine Spiele vor dem Stichtag)", "quality": ["kein Verlauf"], "warnings": []}

    weights = game_weights(games, season)
    minutes = [g["minutes"] for g in games]
    mu0, sd0 = weighted_mean_sd(minutes, weights)
    ppm_idx = [i for i, g in enumerate(games) if g["minutes"] >= MIN_PPM_MINUTES]
    if not ppm_idx:
        return {**base, "ok": False, "reason": f"zu wenig Einsatzzeit (kein Spiel mit mindestens {MIN_PPM_MINUTES:g} Minuten)", "quality": ["kein Verlauf"], "warnings": []}

    if exp_spread is None:
        warnings.append("kein Schnappschuss des Spielmodells: Spread 0 angenommen (kein Blowout-Abschlag über den Durchschnitt hinaus)")
    spread_home = float(exp_spread) if exp_spread is not None else 0.0
    if exp_spread is not None and home is None:
        warnings.append("Heim/Gast unbekannt: Spread 0 angenommen")
        spread_home = 0.0
    team_spread = spread_home if home in (True, None) else -spread_home
    factor = blowout_factor(mu0, team_spread)
    mu = min(MAX_MINUTES, mu0 * factor)

    z = ndtri((np.arange(MINUTE_POINTS) + 0.5) / MINUTE_POINTS)
    m_k = np.clip(mu + sd0 * z, 0.0, MAX_MINUTES)
    w_p = np.array([weights[i] * games[i]["minutes"] for i in ppm_idx]); w_p = w_p / w_p.sum()      # nach Minuten gewichtet: Verhaeltnis-Schaetzer, kurze Einsaetze (hohe, laute ppm) zaehlen weniger
    ppm = np.array([games[i]["points"] / games[i]["minutes"] for i in ppm_idx])
    x = (ppm[:, None] * m_k[None, :]).ravel()                          # Punktewert je (Spiel, Minutenquantil)
    w = (w_p[:, None] * np.full(MINUTE_POINTS, 1.0 / MINUTE_POINTS)[None, :]).ravel()
    h = 1.0 + 0.05 * x
    ns = np.arange(1, MAX_N + 1)
    p = (w[None, :] * (1.0 - ndtr((ns[:, None] - 0.5 - x[None, :]) / h[None, :]))).sum(axis=1)
    p = np.minimum.accumulate(np.clip(p, 0.0, 1.0))                    # nicht steigend in N (numerische Absicherung)
    expected_points = float((w * x).sum())

    n_cur = sum(1 for g in games if g["season"] == season)
    used = {}
    for g in games:
        used[g["season"]] = used.get(g["season"], 0) + 1
    quality = []
    if len(games) < FEW_GAMES:
        quality.append("wenige Spiele")
    if n_cur == 0:
        quality.append("nur Vorsaison")
    last5 = sum(minutes[:5]) / len(minutes[:5])
    if len(games) >= 5 and abs(last5 - mu0) >= ROLE_CHANGE_MINUTES:
        quality.append("Rollenwechsel")
        warnings.append(f"Minuten der letzten 5 Spiele ({last5:.1f}) weichen vom gewichteten Mittel ({mu0:.1f}) ab")
    return {**base, "ok": True, "reason": None,
            "minutes": {"mean": mu, "sd": sd0, "low": max(0.0, mu - sd0), "high": min(MAX_MINUTES, mu + sd0), "base": mu0, "blowout_factor": factor, "role": role_for_minutes(mu0)},
            "expected_points": expected_points, "ppm": float((w_p * ppm).sum()), "p_ge": {int(n): float(v) for n, v in zip(ns, p)},
            "games_used": dict(sorted(used.items())), "quality": quality, "warnings": warnings,
            "context": {"home": home, "exp_spread": exp_spread, "exp_total": exp_total}}


def forecast_game_players(game_key: str, entries: dict, history_games=None) -> dict:
    """Alle Spieler mit Betano-Meilensteinen eines Spiels (engine/player_odds.py) samt Prognose. Rueckgabe {'context', 'players': [{odds-Spieler..., 'forecast': {...}}]}."""
    from engine import player_odds
    ctx = context_for_game(game_key)
    day = game_key.split("|", 1)[0]
    out = []
    for p in player_odds.game_player_odds(entries, game_key):
        is_home = (p["team"] == ctx["home"]) if ctx["home"] else None
        fc = forecast_player(p["person_id"], day, home=is_home, exp_spread=ctx["exp_spread"], exp_total=ctx["exp_total"], name=p["name"])
        out.append({**p, "forecast": fc})
    return {"context": ctx, "players": out}

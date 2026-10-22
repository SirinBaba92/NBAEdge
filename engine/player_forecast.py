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
    """Spread/Total/Teampunkte des Spielmodells aus dem letzten Schnappschuss des Spiels (nur lesen). {'found', 'exp_spread' (positiv = Heim staerker), 'exp_total',
    'home_score', 'away_score' (erwartete Teampunkte; fehlen sie im Schnappschuss, aus Total und Spread: (Total +- Spread) / 2), 'home', 'away'}."""
    g = (snaps.load().get("games") or {}).get(game_key)
    try:
        proj = g["versions"][-1]["projection"]
        spread, total = float(proj["exp_spread"]), float(proj["exp_total"])
        hs = float(proj["home_score"]) if proj.get("home_score") is not None else (total + spread) / 2
        as_ = float(proj["away_score"]) if proj.get("away_score") is not None else (total - spread) / 2
        return {"found": True, "exp_spread": spread, "exp_total": total, "home_score": hs, "away_score": as_, "home": g.get("home"), "away": g.get("away")}
    except (TypeError, KeyError, IndexError, ValueError):
        return {"found": False, "exp_spread": None, "exp_total": None, "home_score": None, "away_score": None, "home": (g or {}).get("home"), "away": (g or {}).get("away")}


# ----------------------------------------------------------------------------- Prognose
def forecast_player(person_id: int, before_date, home: bool | None = None, exp_spread: float | None = None, exp_total: float | None = None,
                    games: list[dict] | None = None, name: str | None = None, minutes_mean_override: float | None = None, points_scale: float = 1.0) -> dict:
    """Prognose fuer ein Spiel am Tag before_date (nur Spiele DAVOR zaehlen). home: Team des Spielers ist Heimteam; exp_spread: erwarteter Spread des Spielmodells
    (positiv = Heim staerker). games: schon gefilterte Spiele (neueste zuerst) statt Zugriff auf den Verlauf (fuer Pruefungen). Wirft nie wegen fehlender Daten.
    minutes_mean_override / points_scale: nur fuer den Teamabgleich (erwartete Minuten ersetzen bzw. Punktewerte mit dem Teamfaktor multiplizieren); ohne sie die rohe Prognose."""
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
    mu = min(MAX_MINUTES, mu0 * factor) if minutes_mean_override is None else min(MAX_MINUTES, max(0.0, float(minutes_mean_override)))

    z = ndtri((np.arange(MINUTE_POINTS) + 0.5) / MINUTE_POINTS)
    m_k = np.clip(mu + sd0 * z, 0.0, MAX_MINUTES)
    w_p = np.array([weights[i] * games[i]["minutes"] for i in ppm_idx]); w_p = w_p / w_p.sum()      # nach Minuten gewichtet: Verhaeltnis-Schaetzer, kurze Einsaetze (hohe, laute ppm) zaehlen weniger
    ppm = np.array([games[i]["points"] / games[i]["minutes"] for i in ppm_idx])
    x = (ppm[:, None] * m_k[None, :]).ravel() * float(points_scale)   # Punktewert je (Spiel, Minutenquantil), ggf. mit Teamfaktor
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


# ----------------------------------------------------------------------------- Teamabgleich (P6b)
# Problem: die Einzelprognosen summieren sich nicht zu den Teampunkten des Spielmodells (22.10.: 76ers Spieler-Summe ohne Bank ca. 143 gegen Team ca. 118, Thunder ca. 105 gegen ca. 122).
# Der erste Versuch (P6b: alle Kaderspieler ab 5 Minuten, Minuten proportional auf 240) kuerzte die Stars zu stark (Mitchell 33,7 -> 24,5 Minuten, weil 13 bis 17 Kaderspieler zusammen
# 300 bis 390 Minuten ergaben). Verfahren seit P6c:
#   1. Rotation = die besten ROTATION_SIZE (10) Spieler des Teams nach erwarteten Minuten (Kaderdatei, auch ohne Betano-Quote). Ab Rang 11 gehen Spieler nicht in die Summe ein,
#      ihre Prognose bleibt roh (Hinweis).
#   2. Minuten: die 5 Spieler mit den meisten Minuten behalten sie, hoechstens STARTER_MINUTES_CAP (36). Die Plaetze 6 bis 10 (Bank) werden so skaliert, dass die Summe aller 10 genau 240
#      ergibt, Faktor zwischen BENCH_SCALE_MIN (0,3) und BENCH_SCALE_MAX (1,0). Reicht das nicht, werden alle 10 proportional auf 240 skaliert, hoechstens MINUTES_CAP (42) je Spieler (Hinweis).
#   3. Punkte: Faktor f = Teampunkte / Summe der erwarteten Punkte der Rotation (mit den neuen Minuten). f ** TEAM_MATCH_STRENGTH, begrenzt auf F_MIN..F_MAX (0,6..1,4); ausserhalb
#      Hinweis "Teamabgleich stark". Spieler ohne Verlauf zaehlen mit NO_HISTORY_MINUTES und dem Liga-Durchschnitt der Punkte pro Minute (2025-26).
#   4. P(Punkte >= N) wird mit den neuen Minuten und dem Faktor neu berechnet.
# Die rohe Prognose bleibt unveraendert in "expected_points" / "p_ge" / "minutes"; der Abgleich steht in den Feldern *_raw und *_adjusted.
TEAM_MATCH_STRENGTH = 1.0         # Exponent auf f: 1.0 = voller Abgleich, 0 = aus (dann ist "angepasst" = roh, auch ohne Minutenverteilung)
TEAM_MIN_MINUTES = 5.0            # nur Spieler mit mindestens so vielen erwarteten Minuten kommen fuer die Rotation in Frage
TEAM_MINUTES = 240.0
ROTATION_SIZE = 10
STARTER_COUNT = 5
STARTER_MINUTES_CAP = 36.0
BENCH_SCALE_MIN, BENCH_SCALE_MAX = 0.3, 1.0
MINUTES_CAP = 42.0                # Obergrenze je Spieler im Sonderfall (proportionale Skalierung)
F_MIN, F_MAX = 0.6, 1.4
NO_HISTORY_MINUTES = 10.0
FALLBACK_LEAGUE_PPM = 0.49
_league_ppm_cache: dict = {}


def league_ppm() -> float:
    """Liga-Durchschnitt der Punkte pro Minute (Summe Punkte / Summe Minuten) aus 2025-26; Rueckfall FALLBACK_LEAGUE_PPM."""
    if "v" not in _league_ppm_cache:
        try:
            rows = ph.season_rows("2025-26", with_recorder=False)
            minutes = sum(r["minutes"] for r in rows)
            _league_ppm_cache["v"] = sum(r["points"] for r in rows) / minutes if minutes > 0 else FALLBACK_LEAGUE_PPM
        except Exception:
            _league_ppm_cache["v"] = FALLBACK_LEAGUE_PPM
    return _league_ppm_cache["v"]


def scale_minutes(minutes: list[float], target: float = TEAM_MINUTES, cap: float = MINUTES_CAP) -> list[float]:
    """Alle Minuten proportional auf die Summe target; wer dabei ueber cap kaeme, bekommt cap, der Rest verteilt sich auf die anderen."""
    fixed: set[int] = set()
    for _ in range(len(minutes)):
        free = [i for i in range(len(minutes)) if i not in fixed]
        s_free = sum(minutes[i] for i in free)
        if not free or s_free <= 0:
            break
        k = (target - cap * len(fixed)) / s_free
        over = {i for i in free if minutes[i] * k > cap}
        if not over:
            return [cap if i in fixed else minutes[i] * k for i in range(len(minutes))]
        fixed |= over
    return [cap if i in fixed else minutes[i] for i in range(len(minutes))]


def distribute_minutes(minutes: list[float]) -> tuple[list[float], str]:
    """Minutenverteilung der Rotation (erwartete Minuten, absteigend sortiert). Rueckgabe (neue Minuten in gleicher Reihenfolge, Hinweis; leer im Normalfall).
    Stammspieler (die ersten STARTER_COUNT) behalten ihre Minuten (hoechstens STARTER_MINUTES_CAP); die Bank wird auf die Summe 240 skaliert (Faktor 0,3 bis 1,0).
    Sonderfall (Faktor ausserhalb 0,3..1,0): alle proportional auf 240, hoechstens MINUTES_CAP je Spieler."""
    starters = [min(m, STARTER_MINUTES_CAP) for m in minutes[:STARTER_COUNT]]
    bench = minutes[STARTER_COUNT:]
    s_start, s_bench = sum(starters), sum(bench)
    if bench and s_bench > 0:
        k = (TEAM_MINUTES - s_start) / s_bench
        if BENCH_SCALE_MIN <= k <= BENCH_SCALE_MAX:
            return starters + [m * k for m in bench], ""
        why = (f"Bank müsste mit Faktor {k:.2f} skaliert werden (erlaubt {BENCH_SCALE_MIN:g} bis {BENCH_SCALE_MAX:g})")
    else:
        why = "keine Bank in der Rotation"
    return scale_minutes(list(minutes)), f"Sonderfall: {why}, alle Rotationsspieler proportional auf {TEAM_MINUTES:g} Minuten (höchstens {MINUTES_CAP:g})"


def team_match(team: str, is_home: bool, ctx: dict, day: str, extra_ids: dict | None = None) -> dict:
    """Teamabgleich fuer ein Team (Verfahren siehe oben). Rueckgabe: {'info': {...Team-Kennzahlen...}, 'adjusted': {person_id: Prognose mit Abgleich (nur Rotation)},
    'raw': {person_id: rohe Prognose}, 'rank': {person_id: Rang nach erwarteten Minuten}}. Ohne Schnappschuss oder Teampunkte: kein Abgleich (Hinweis "kein Teamabgleich")."""
    info = {"team": team, "matched": False, "note": "kein Teamabgleich", "team_points": None, "player_sum": None, "player_sum_scaled": None, "factor": None, "factor_applied": None,
            "strong": False, "minutes_before": None, "minutes_after": None, "members": 0, "rotation": [], "out_of_rotation": [], "no_history": [], "minutes_note": "", "minutes_new": {}}
    team_points = ctx.get("home_score") if is_home else ctx.get("away_score")
    if not ctx.get("found") or team_points is None:
        return {"info": info, "adjusted": {}, "raw": {}, "rank": {}}
    info["team_points"] = float(team_points)
    from data import rosters
    roster = (rosters.load().get("teams") or {}).get(team) or []
    people = {int(p["person_id"]): p["name"] for p in roster}
    for pid, name in (extra_ids or {}).items():
        people.setdefault(int(pid), name)
    spread = ctx["exp_spread"]
    cands = []                                     # {'pid', 'name', 'fc' (roh) | None, 'minutes'}
    for pid, name in people.items():
        fc = forecast_player(pid, day, home=is_home, exp_spread=spread, exp_total=ctx.get("exp_total"), name=name)
        if fc["ok"]:
            if fc["minutes"]["mean"] >= TEAM_MIN_MINUTES:
                cands.append({"pid": pid, "name": name, "fc": fc, "minutes": fc["minutes"]["mean"]})
        else:
            cands.append({"pid": pid, "name": name, "fc": None, "minutes": NO_HISTORY_MINUTES})
    cands.sort(key=lambda m: (-m["minutes"], m["name"]))
    rotation, rest = cands[:ROTATION_SIZE], cands[ROTATION_SIZE:]
    info["members"] = len(rotation)
    info["rotation"] = [m["name"] for m in rotation]
    info["out_of_rotation"] = [m["name"] for m in rest]
    info["no_history"] = [m["name"] for m in rotation if not m["fc"]]
    rank = {m["pid"]: i + 1 for i, m in enumerate(cands)}
    raw = {m["pid"]: m["fc"] for m in cands if m["fc"]}
    if not rotation:
        info["note"] = "kein Teamabgleich (keine Spieler mit Verlauf im Kader)"
        return {"info": info, "adjusted": {}, "raw": raw, "rank": rank}
    info["player_sum"] = sum(m["fc"]["expected_points"] if m["fc"] else m["minutes"] * league_ppm() for m in rotation)
    info["minutes_before"] = sum(m["minutes"] for m in rotation)
    if TEAM_MATCH_STRENGTH <= 0:
        info.update(note="Teamabgleich aus (TEAM_MATCH_STRENGTH = 0)", minutes_after=info["minutes_before"], player_sum_scaled=info["player_sum"], factor=1.0, factor_applied=1.0)
        return {"info": info, "adjusted": dict(raw), "raw": raw, "rank": rank}
    new_minutes, minutes_note = distribute_minutes([m["minutes"] for m in rotation])
    info["minutes_note"] = minutes_note
    info["minutes_after"] = sum(new_minutes)
    for m, nm in zip(rotation, new_minutes):
        m["minutes_new"] = nm
        info["minutes_new"][m["name"]] = nm
    scaled = {m["pid"]: (forecast_player(m["pid"], day, home=is_home, exp_spread=spread, name=m["name"], minutes_mean_override=m["minutes_new"])["expected_points"]
                         if m["fc"] else m["minutes_new"] * league_ppm()) for m in rotation}
    s_sum = sum(scaled.values())
    info["player_sum_scaled"] = s_sum
    if s_sum <= 0:
        info["note"] = "kein Teamabgleich (Summe der erwarteten Punkte 0)"
        return {"info": info, "adjusted": {}, "raw": raw, "rank": rank}
    f = info["team_points"] / s_sum
    f_pow = f ** TEAM_MATCH_STRENGTH
    f_eff = min(F_MAX, max(F_MIN, f_pow))
    info.update(matched=True, note="", factor=f, factor_applied=f_eff, strong=(f_pow != f_eff))
    if info["strong"]:
        info["note"] = f"Teamabgleich stark (Faktor {f_pow:.2f} auf {f_eff:.2f} begrenzt)"
    adjusted = {m["pid"]: forecast_player(m["pid"], day, home=is_home, exp_spread=spread, name=m["name"], minutes_mean_override=m["minutes_new"], points_scale=f_eff)
                for m in rotation if m["fc"]}
    return {"info": info, "adjusted": adjusted, "raw": raw, "rank": rank}


def forecast_game_players(game_key: str, entries: dict, history_games=None) -> dict:
    """Alle Spieler mit Betano-Meilensteinen eines Spiels (engine/player_odds.py) samt Prognose und Teamabgleich.
    Rueckgabe {'context', 'teams': {Teamname: Kennzahlen}, 'players': [{odds-Spieler..., 'forecast': {...}}]}. Spieler ausserhalb der Rotation (Rang 11+) bleiben roh. Jede Prognose traegt zusaetzlich expected_points_raw / _adjusted und
    p_ge_raw / p_ge_adjusted (ohne Abgleich oder bei fehlendem Schnappschuss sind beide gleich; Hinweis in 'team_note')."""
    from engine import player_odds
    ctx = context_for_game(game_key)
    day = game_key.split("|", 1)[0]
    odds_players = player_odds.game_player_odds(entries, game_key)
    teams = {}
    for team in sorted({p["team"] for p in odds_players if p["team"]}):
        is_home = (team == ctx["home"]) if ctx["home"] else None
        ids = {p["person_id"]: p["name"] for p in odds_players if p["team"] == team}
        teams[team] = team_match(team, bool(is_home), ctx, day, ids) if is_home is not None else \
            {"info": {"team": team, "matched": False, "note": "kein Teamabgleich", "team_points": None, "factor": None}, "adjusted": {}, "raw": {}}
    out = []
    for p in odds_players:
        is_home = (p["team"] == ctx["home"]) if ctx["home"] else None
        fc = forecast_player(p["person_id"], day, home=is_home, exp_spread=ctx["exp_spread"], exp_total=ctx["exp_total"], name=p["name"])
        t = teams.get(p["team"]) or {"info": {"matched": False, "note": "kein Teamabgleich"}, "adjusted": {}, "rank": {}}
        if fc["ok"]:
            adj = t["adjusted"].get(int(p["person_id"]))
            fc["expected_points_raw"], fc["p_ge_raw"] = fc["expected_points"], fc["p_ge"]
            fc["expected_points_adjusted"] = adj["expected_points"] if adj else fc["expected_points"]
            fc["p_ge_adjusted"] = adj["p_ge"] if adj else fc["p_ge"]
            fc["minutes_adjusted"] = adj["minutes"]["mean"] if adj else fc["minutes"]["mean"]
            r = t.get("rank", {}).get(int(p["person_id"]))
            if adj and t["info"].get("matched"):
                fc["team_note"] = t["info"].get("note") or ""
            elif t["info"].get("matched") and r and r > ROTATION_SIZE:
                fc["team_note"] = f"nicht in der Rotation (Rang {r} nach Minuten): Prognose roh, nicht im Teamabgleich"
            else:
                fc["team_note"] = t["info"].get("note") or "kein Teamabgleich"
        out.append({**p, "forecast": fc})
    return {"context": ctx, "teams": {k: v["info"] for k, v in teams.items()}, "players": out}

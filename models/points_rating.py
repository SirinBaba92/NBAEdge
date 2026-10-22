"""
NBAEdge Punkte-Rating (Modell v2, Test)
---------------------------------------
Rating in Punkten statt ELO: Update auf den Margin-Fehler statt auf Sieg/Niederlage.

- rating[team]: Punkte ueber/unter Liga-Durchschnitt (0 = Durchschnitt)
- Spread (positiv = Heimteam ist Favorit) = rating_home - rating_away + hca
- Update je Spiel: err = clip(margin, +-cap) - spread; rating_home += k*err; rating_away -= k*err
- Saisonuebernahme: beim ersten Spiel/Zugriff in einer neuen Saison werden alle Ratings um den
  Anteil r Richtung 0 gezogen (rating *= 1 - r). Die Saison steht im Modell (self.season).
- Siegwahrscheinlichkeit = Phi(spread / sigma), begrenzt auf [MIN_WIN_PROB, MAX_WIN_PROB]
- hca und sigma werden zu Saisonbeginn aus den letzten CALIB_SEASONS abgeschlossenen
  Regular-Season-Saisons neu bestimmt (keine freien Parameter)
- Total: zwei Modi ('dev' = Liga-Niveau + Team-Abweichung, 'ema' = Team-EMA wie das alte Modell)
- Fortschreiben: update_with_games() verarbeitet nur neue, beendete Spiele (Dedupe nach Spiel-ID)

Das alte EloEngine-Modell (models/elo.py, data/elo_model.pkl) bleibt unberuehrt.
"""

from __future__ import annotations

import math
import pickle
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from config.settings import MIN_WIN_PROB, MAX_WIN_PROB

VERSION = 2
MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "points_rating_v2.pkl"
HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "model_history"
CALIB_SEASONS = 4

# Startwerte aus der Analyse (ELO_ANALYSE.md); die endgueltigen Werte stammen aus dem
# verschachtelten Walk-forward-Backtest (PHASE_B_BERICHT.md) und stehen im gespeicherten Modell.
DEFAULT_PARAMS = {
    "r": 0.4,            # Saisonuebernahme: Anteil, der pro Sommer verschwindet
    "k": 0.05,           # Lernrate je Spiel (Punkte pro Punkt Fehler)
    "cap": 25.0,         # Margin-Cap
    "playoff_w": 1.0,    # Gewicht der Playoff-Spiele im Rating-Update
    # Total
    "tmode": "dev",      # 'dev' oder 'ema'
    "t_alpha": 0.10,     # EMA-Rate der Team-Abweichung / des Team-Totals
    "t_rc": 0.5,         # Saisonuebernahme der Team-Total-Abweichung
    "t_po": False,       # Playoff-Spiele im Total-Teil beruecksichtigen
    "L_alpha": 0.02,     # EMA-Rate des Liga-Niveaus (nur Regular Season)
}
INIT_HCA = 2.3
INIT_SIGMA = 13.0
INIT_TOTAL = 225.0


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def season_for_date(d: date) -> int:
    """BallDontLie-Saison (Startjahr): ab Oktober die neue Saison."""
    return d.year if d.month >= 10 else d.year - 1


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def is_finished(g: dict) -> bool:
    return (
        g.get("status") == "Final"
        and not g.get("postponed")
        and g.get("home_team_score") is not None
        and g.get("visitor_team_score") is not None
    )


class PointsRatingModel:
    def __init__(self, params: dict | None = None):
        self.version = VERSION
        self.params = dict(DEFAULT_PARAMS)
        if params:
            self.params.update(params)
        self.ratings: dict[str, float] = defaultdict(float)
        self.gp: dict[str, int] = defaultdict(int)           # Regular-Season-Spiele der aktuellen Saison
        self.tdev: dict[str, float] = {}                      # Team-Abweichung ('dev') bzw. Team-Total ('ema')
        self.L = INIT_TOTAL                                   # Liga-Niveau des Totals
        self.hca = INIT_HCA
        self.sigma = INIT_SIGMA
        self.season: int | None = None
        self.processed_ids: set[int] = set()
        self.last_date: date | None = None
        self._hist: list[tuple[int, float, float]] = []       # (season, rdiff_pre, margin), nur Regular Season
        self._season_total_sum = 0.0
        self._season_total_n = 0

    # ------------------------------------------------------------------ #
    #  Saisonwechsel                                                       #
    # ------------------------------------------------------------------ #
    def ensure_season(self, season: int) -> bool:
        """Wendet beim ersten Zugriff in einer neuen Saison die Uebernahme an. True, wenn angewendet."""
        if self.season is None:
            self.season = season
            return False
        if season <= self.season:
            return False
        p = self.params
        league_mean = (
            self._season_total_sum / self._season_total_n if self._season_total_n else self.L
        )
        for t in list(self.ratings):
            self.ratings[t] *= 1.0 - p["r"]
        if p["tmode"] == "dev":
            for t in list(self.tdev):
                self.tdev[t] *= 1.0 - p["t_rc"]
        else:
            for t in list(self.tdev):
                self.tdev[t] = league_mean + (1.0 - p["t_rc"]) * (self.tdev[t] - league_mean)
        self.gp = defaultdict(int)
        self._season_total_sum = 0.0
        self._season_total_n = 0
        self.season = season
        self._recalibrate()
        return True

    def _recalibrate(self) -> None:
        """hca und sigma aus den letzten CALIB_SEASONS abgeschlossenen Saisons (nur Regular Season)."""
        if self.season is None:
            return
        rows = [(r, m) for s, r, m in self._hist if self.season - CALIB_SEASONS <= s < self.season]
        if len(rows) < 300:
            return
        rd = np.array([r for r, _ in rows])
        mg = np.array([m for _, m in rows])
        self.hca = float(np.mean(mg - rd))
        self.sigma = float(np.std(mg - rd - self.hca))

    # ------------------------------------------------------------------ #
    #  Prognose                                                            #
    # ------------------------------------------------------------------ #
    def _total_for(self, home: str, away: str) -> float:
        if self.params["tmode"] == "dev":
            return self.L + (self.tdev.get(home, 0.0) + self.tdev.get(away, 0.0)) / 2.0
        return (self.tdev.get(home, self.L) + self.tdev.get(away, self.L)) / 2.0

    def win_prob_from_spread(self, spread: float) -> float:
        p = _phi(spread / self.sigma)
        return min(MAX_WIN_PROB, max(MIN_WIN_PROB, p))

    def predict(self, home: str, away: str, game_date: date | None = None) -> dict:
        """Prognose. Die Saison ergibt sich aus dem Datum (US-Datum!); bei neuer Saison wird die
        Uebernahme beim ersten Zugriff angewendet und im Modell gespeichert (self.season)."""
        game_date = game_date or date.today()
        self.ensure_season(season_for_date(game_date))
        rh, ra = self.ratings.get(home, 0.0), self.ratings.get(away, 0.0)
        spread = rh - ra + self.hca
        total = self._total_for(home, away)
        p_home = self.win_prob_from_spread(spread)
        return {
            "home_team": home,
            "away_team": away,
            "spread": round(spread, 1),               # positiv = Heimteam ist Favorit
            "home_win_prob": round(p_home, 4),
            "away_win_prob": round(1.0 - p_home, 4),
            "expected_total": round(total, 1),
            "home_score": round((total + spread) / 2.0, 1),
            "away_score": round((total - spread) / 2.0, 1),
            "home_rating": round(rh, 2),
            "away_rating": round(ra, 2),
            "rating_season": self.season,
            "model_version": self.version,
        }

    # ------------------------------------------------------------------ #
    #  Ein Spiel verarbeiten                                               #
    # ------------------------------------------------------------------ #
    def process_game(self, g: dict) -> dict:
        """Verarbeitet ein beendetes Spiel. Gibt die Vorhersage VOR dem Update zurueck."""
        p = self.params
        self.ensure_season(int(g["season"]))
        home = g["home_team"]["full_name"]
        away = g["visitor_team"]["full_name"]
        hp, ap = int(g["home_team_score"]), int(g["visitor_team_score"])
        gd = _parse_date(g["date"])
        post = bool(g.get("postseason", False))
        margin, total = hp - ap, hp + ap

        rdiff = self.ratings[home] - self.ratings[away]
        spread = rdiff + self.hca
        total_pred = self._total_for(home, away)
        rec = {
            "id": g.get("id"), "season": int(g["season"]), "post": int(post),
            "gp_h": self.gp[home], "gp_a": self.gp[away],
            "rdiff": rdiff, "hca": self.hca, "sigma": self.sigma,
            "total_pred": total_pred, "margin": margin, "total": total,
        }

        # Rating-Update
        err = max(-p["cap"], min(p["cap"], float(margin))) - spread
        kk = p["k"] * (p["playoff_w"] if post else 1.0)
        self.ratings[home] += kk * err
        self.ratings[away] -= kk * err

        # Total-Update
        if (not post) or p["t_po"]:
            a = p["t_alpha"]
            if p["tmode"] == "dev":
                for t in (home, away):
                    self.tdev[t] = (1 - a) * self.tdev.get(t, 0.0) + a * (total - self.L)
            else:
                for t in (home, away):
                    self.tdev[t] = (1 - a) * self.tdev.get(t, self.L) + a * total
        if not post:
            self.L = (1 - p["L_alpha"]) * self.L + p["L_alpha"] * total
            self._season_total_sum += total
            self._season_total_n += 1
            self._hist.append((int(g["season"]), rdiff, float(margin)))
            self.gp[home] += 1
            self.gp[away] += 1

        if g.get("id") is not None:
            self.processed_ids.add(g["id"])
        if self.last_date is None or gd > self.last_date:
            self.last_date = gd
        return rec

    # ------------------------------------------------------------------ #
    #  Taegliches Fortschreiben                                            #
    # ------------------------------------------------------------------ #
    def update_with_games(self, games: list[dict]) -> dict:
        """Verarbeitet nur neue, beendete Spiele (status == 'Final', nicht verschoben), dedupliziert nach
        Spiel-ID, in Datums-/ID-Reihenfolge. Gibt eine kleine Statistik zurueck."""
        stats = {"received": len(games), "not_final": 0, "duplicates": 0, "processed": 0}
        fresh, seen = [], set()
        for g in games:
            if not is_finished(g):
                stats["not_final"] += 1
                continue
            gid = g.get("id")
            if gid in self.processed_ids or gid in seen:
                stats["duplicates"] += 1
                continue
            seen.add(gid)
            fresh.append(g)
        fresh.sort(key=lambda g: (g["date"][:10], g.get("id") or 0))
        for g in fresh:
            self.process_game(g)
            stats["processed"] += 1
        return stats

    def next_fetch_start(self, overlap_days: int = 2) -> date | None:
        """Startdatum (US-Datum) fuer die naechste Abfrage; leichte Ueberlappung, Dedupe uebernimmt."""
        if self.last_date is None:
            return None
        return self.last_date - timedelta(days=overlap_days)

    # ------------------------------------------------------------------ #
    #  Speichern / Laden                                                   #
    # ------------------------------------------------------------------ #
    def save(self, path: Path | None = None, dated_copy: bool = True) -> Path:
        path = Path(path) if path else MODEL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)
        if dated_copy:
            hist_dir = path.parent / "model_history" if path != MODEL_PATH else HISTORY_DIR
            hist_dir.mkdir(parents=True, exist_ok=True)
            stamp = (self.last_date or date.today()).isoformat()
            shutil.copy2(path, hist_dir / f"{path.stem}_{stamp}{path.suffix}")
        return path

    @staticmethod
    def load(path: Path | None = None) -> "PointsRatingModel":
        path = Path(path) if path else MODEL_PATH
        with open(path, "rb") as f:
            obj = pickle.load(f)
        if not isinstance(obj, PointsRatingModel) or getattr(obj, "version", None) != VERSION:
            raise ValueError(
                f"{path} ist kein PointsRatingModel v{VERSION} (version={getattr(obj, 'version', None)})"
            )
        return obj

    @staticmethod
    def exists(path: Path | None = None) -> bool:
        return (Path(path) if path else MODEL_PATH).exists()


def build_from_games(games: list[dict], params: dict | None = None) -> PointsRatingModel:
    """Baut ein Modell aus beendeten Spielen (chronologisch). Liest nichts aus dem Netz."""
    m = PointsRatingModel(params)
    m.update_with_games(games)
    return m

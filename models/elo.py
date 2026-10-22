"""
NBAEdge ELO Engine
------------------
- Elo rating with offense/defense split per team
- Home Court Advantage (calibrated from data)
- Rest-Days Factor (Back-to-Back detection)
- Form Momentum (last 10 games weighted)
- Score-based point distribution
- Logistic regression on Elo-diff → Win Probability
"""

import numpy as np
import pandas as pd
from datetime import datetime, date
from collections import defaultdict
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
import os
import pickle
import shutil
from datetime import timedelta
from pathlib import Path

from config.settings import (
    ELO_K_FACTOR, ELO_START, HOME_COURT_ADVANTAGE,
    REST_DAYS_WEIGHT, FORM_WINDOW, SEASONS_TO_LOAD,
    MIN_WIN_PROB, MAX_WIN_PROB,
)

MODEL_PATH = Path(__file__).parent.parent / "data" / "elo_model.pkl"
HISTORY_DIR = Path(__file__).parent.parent / "data" / "model_history"


def _parse_date(d: str) -> date:
    return datetime.strptime(d[:10], "%Y-%m-%d").date()


class EloEngine:
    def __init__(self):
        self.ratings: dict[str, float] = {}
        self.off_ratings: dict[str, float] = defaultdict(float)
        self.def_ratings: dict[str, float] = defaultdict(float)
        self.last_game: dict[str, date] = {}
        self.form: dict[str, list] = defaultdict(list)  # 1=win 0=loss
        self.hca: float = HOME_COURT_ADVANTAGE
        self.lr_model = None
        self.scaler = StandardScaler()
        self._training_X = []
        self._training_y = []
        # Fortschreiben: IDs aller verarbeiteten Spiele und Datum des letzten verarbeiteten Spiels.
        # (Pickles aus der Zeit vor dem Fortschreiben haben diese Felder nicht, siehe __setstate__.)
        self.processed_ids: set | None = set()
        self.last_processed_date: date | None = None
        # Spiele, die beim Abruf noch nicht beendet waren (id -> Datum). Sie bestimmen das Startdatum der
        # naechsten Abfrage mit, damit ein spaet beendetes Spiel nicht aus dem Zeitfenster faellt.
        self.pending: dict = {}

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Alte Pickles: unbekannt (None) statt leer, damit das Fortschreiben nicht still falsch rechnet
        self.__dict__.setdefault("processed_ids", None)
        self.__dict__.setdefault("last_processed_date", None)
        self.__dict__.setdefault("pending", {})

    # ------------------------------------------------------------------ #
    #  Rest-Days Factor                                                    #
    # ------------------------------------------------------------------ #
    def _rest_factor(self, team: str, game_date: date) -> float:
        """Back-to-back = negative penalty; 3+ days rest = small bonus."""
        if team not in self.last_game:
            return 0.0
        days = (game_date - self.last_game[team]).days
        if days == 1:   return -REST_DAYS_WEIGHT * 100   # B2B
        if days == 2:   return 0.0
        if days >= 3:   return REST_DAYS_WEIGHT * 30
        return 0.0

    # ------------------------------------------------------------------ #
    #  Form Momentum                                                       #
    # ------------------------------------------------------------------ #
    def _form_score(self, team: str) -> float:
        """Weighted win-rate over last FORM_WINDOW games."""
        history = self.form[team][-FORM_WINDOW:]
        if not history:
            return 0.5
        weights = np.arange(1, len(history) + 1, dtype=float)
        return float(np.dot(history, weights) / weights.sum())

    # ------------------------------------------------------------------ #
    #  ELO Expected Score                                                  #
    # ------------------------------------------------------------------ #
    def _expected(self, ra: float, rb: float) -> float:
        return 1 / (1 + 10 ** ((rb - ra) / 400))

    # ------------------------------------------------------------------ #
    #  Score-based K (Margin of Victory multiplier)                        #
    # ------------------------------------------------------------------ #
    def _mov_multiplier(self, pts_for: int, pts_against: int) -> float:
        margin = abs(pts_for - pts_against)
        # Diminishing returns formula (similar to 538)
        return np.log(margin + 1) * (2.2 / 1.0)

    # ------------------------------------------------------------------ #
    #  Process One Game                                                    #
    # ------------------------------------------------------------------ #
    def process_game(self, game: dict):
        home = game["home_team"]["full_name"]
        away = game["visitor_team"]["full_name"]
        h_pts = int(game["home_team_score"])
        a_pts = int(game["visitor_team_score"])
        gdate = _parse_date(game["date"])

        # Pre-game ratings snapshot for training
        h_rest = self._rest_factor(home, gdate)
        a_rest = self._rest_factor(away, gdate)
        h_form = self._form_score(home)
        a_form = self._form_score(away)
        h_elo  = self.ratings.get(home, 1500.0) + self.hca + h_rest + (h_form - 0.5) * 40
        a_elo  = self.ratings.get(away, 1500.0)             + a_rest + (a_form - 0.5) * 40

        elo_diff = h_elo - a_elo
        h_exp = self._expected(h_elo, a_elo)

        home_won = 1 if h_pts > a_pts else 0

        # Store for logistic regression training
        self._training_X.append([elo_diff, h_form - a_form, h_rest - a_rest])
        self._training_y.append(home_won)

        # Update ELO
        mov = self._mov_multiplier(h_pts, a_pts)
        k = ELO_K_FACTOR * mov
        self.ratings[home] = self.ratings.get(home, 1500.0) + k * (home_won - h_exp)
        self.ratings[away] = self.ratings.get(away, 1500.0) + k * ((1 - home_won) - (1 - h_exp))

        # Update offense/defense ratings (points-per-game rolling).
        # Playoff-Spiele (Feld postseason) werden NICHT eingerechnet: In den Playoffs wird deutlich
        # weniger gepunktet (2021-25: 8 bis 17 Punkte weniger Total), das druecken die Werte der
        # Playoff-Teams sonst bis in den naechsten Saisonstart (PHASE_B_BERICHT.md, Abschnitt 4).
        # ELO, Form und Ruhetage laufen weiterhin mit Playoffs.
        if not game.get("postseason", False):
            alpha = 0.1
            self.off_ratings[home] = (1 - alpha) * self.off_ratings.get(home, 0.0) + alpha * h_pts
            self.def_ratings[home] = (1 - alpha) * self.def_ratings.get(home, 0.0) + alpha * a_pts
            self.off_ratings[away] = (1 - alpha) * self.off_ratings.get(away, 0.0) + alpha * a_pts
            self.def_ratings[away] = (1 - alpha) * self.def_ratings.get(away, 0.0) + alpha * h_pts

        # Update form
        self.form[home].append(home_won)
        self.form[away].append(1 - home_won)

        # Update last game date (nie rueckwaerts, falls ein Spiel nachtraeglich verarbeitet wird)
        for t in (home, away):
            if t not in self.last_game or gdate > self.last_game[t]:
                self.last_game[t] = gdate

        # Verarbeitete Spiele merken (Fortschreiben ueberspringt sie)
        if self.processed_ids is not None and game.get("id") is not None:
            self.processed_ids.add(game["id"])
        if self.last_processed_date is None or gdate > self.last_processed_date:
            self.last_processed_date = gdate

    # ------------------------------------------------------------------ #
    #  Fortschreiben (taegliches Update ohne Neutraining)                  #
    # ------------------------------------------------------------------ #
    def update_with_games(self, games: list[dict]) -> dict:
        """Verarbeitet nur neue, beendete Spiele (status == 'Final', nicht verschoben, Scores vorhanden),
        dedupliziert nach Spiel-ID (gegen gespeicherte IDs und innerhalb des Batches), in Datums-/ID-Reihenfolge.
        Die Logistik (lr_model/scaler) bleibt unveraendert."""
        if self.processed_ids is None:
            raise RuntimeError(
                "Dieses Modell kennt seine verarbeiteten Spiel-IDs nicht (altes Pickle). "
                "Bitte einmal `python train.py` ausfuehren, danach ist Fortschreiben moeglich."
            )
        stats = {"received": len(games), "not_final": 0, "duplicates": 0, "processed": 0}
        fresh, seen = [], set()
        for g in games:
            finished = (
                g.get("status") == "Final"
                and not g.get("postponed")
                and g.get("home_team_score") is not None
                and g.get("visitor_team_score") is not None
            )
            if not finished:
                stats["not_final"] += 1
                if g.get("id") is not None and g.get("date"):
                    self.pending[g["id"]] = _parse_date(g["date"])
                continue
            gid = g.get("id")
            if gid is None or gid in self.processed_ids or gid in seen:
                stats["duplicates"] += 1
                continue
            seen.add(gid)
            fresh.append(g)
        fresh.sort(key=lambda g: (g["date"][:10], g["id"]))
        for g in fresh:
            self.process_game(g)
            self.pending.pop(g["id"], None)
            stats["processed"] += 1
        # Nie beendete Spiele nach 14 Tagen vergessen (z. B. dauerhaft abgesagt)
        asof = self.ratings_as_of()
        if asof:
            self.pending = {i: d for i, d in self.pending.items()
                            if i not in self.processed_ids and d >= asof - timedelta(days=14)}
        return stats

    def ratings_as_of(self) -> date | None:
        """Datum (US-Spieldatum) des letzten verarbeiteten Spiels."""
        if self.last_processed_date is not None:
            return self.last_processed_date
        return max(self.last_game.values()) if self.last_game else None

    def next_fetch_start(self, overlap_days: int = 2) -> date | None:
        """Startdatum fuer die naechste Abfrage (leichte Ueberlappung, Deduplizierung faengt sie ab)."""
        d = self.ratings_as_of()
        if not d:
            return None
        start = d - timedelta(days=overlap_days)
        if self.pending:
            start = min(start, min(self.pending.values()))
        return start

    # ------------------------------------------------------------------ #
    #  Train Logistic Regression                                           #
    # ------------------------------------------------------------------ #
    def fit_lr(self):
        X = np.array(self._training_X)
        y = np.array(self._training_y)
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        base = LogisticRegression(max_iter=1000)
        self.lr_model = CalibratedClassifierCV(base, cv=5, method="isotonic")
        self.lr_model.fit(X_scaled, y)
        print(f"  LR model trained on {len(y)} games.")

    # ------------------------------------------------------------------ #
    #  Predict Win Probability for Upcoming Game                           #
    # ------------------------------------------------------------------ #
    def predict(self, home: str, away: str, game_date: date = None) -> dict:
        if game_date is None:
            game_date = date.today()

        h_rest = self._rest_factor(home, game_date)
        a_rest = self._rest_factor(away, game_date)
        h_form = self._form_score(home)
        a_form = self._form_score(away)
        h_elo  = self.ratings[home] + self.hca + h_rest + (h_form - 0.5) * 40
        a_elo  = self.ratings[away]             + a_rest + (a_form - 0.5) * 40
        elo_diff = h_elo - a_elo

        features = np.array([[elo_diff, h_form - a_form, h_rest - a_rest]])

        if self.lr_model:
            features_scaled = self.scaler.transform(features)
            h_win_prob = float(self.lr_model.predict_proba(features_scaled)[0][1])
        else:
            h_win_prob = float(self._expected(h_elo, a_elo))

        # Begrenzung erst beim Auslesen (das gespeicherte Modell bleibt unveraendert):
        # Isotonik kann sonst exakt 0 % / 100 % liefern.
        h_win_prob = min(MAX_WIN_PROB, max(MIN_WIN_PROB, h_win_prob))

        # Expected total points (offense vs defense matchup)
        h_exp_pts = (self.off_ratings[home] + self.def_ratings[away]) / 2
        a_exp_pts = (self.off_ratings[away] + self.def_ratings[home]) / 2
        exp_total = h_exp_pts + a_exp_pts

        return {
            "home_team": home,
            "away_team": away,
            "home_win_prob": round(h_win_prob, 4),
            "away_win_prob": round(1 - h_win_prob, 4),
            "home_elo": round(h_elo, 1),
            "away_elo": round(a_elo, 1),
            "elo_diff": round(elo_diff, 1),
            "home_form": round(h_form, 3),
            "away_form": round(a_form, 3),
            "home_rest_days": (game_date - self.last_game.get(home, game_date)).days if home in self.last_game else None,
            "away_rest_days": (game_date - self.last_game.get(away, game_date)).days if away in self.last_game else None,
            "expected_total": round(exp_total, 1),
        }

    # ------------------------------------------------------------------ #
    #  Serialization                                                       #
    # ------------------------------------------------------------------ #
    def save(self, path: Path | None = None, dated_copy: bool = False) -> Path:
        """Speichert atomar (erst .tmp, dann ersetzen). Mit dated_copy zusaetzlich eine Kopie
        data/model_history/elo_model_<Stand>.pkl (Stand = letztes verarbeitetes Spieldatum)."""
        path = Path(path) if path else MODEL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(self, f)
        os.replace(tmp, path)
        print(f"  Model saved → {path}")
        if dated_copy:
            hist = HISTORY_DIR if path == MODEL_PATH else path.parent / "model_history"
            hist.mkdir(parents=True, exist_ok=True)
            stamp = (self.ratings_as_of() or date.today()).isoformat()
            shutil.copy2(path, hist / f"{path.stem}_{stamp}{path.suffix}")
            print(f"  Datumskopie → {hist / f'{path.stem}_{stamp}{path.suffix}'}")
        return path

    @staticmethod
    def load(path: Path | None = None) -> "EloEngine":
        with open(Path(path) if path else MODEL_PATH, "rb") as f:
            return pickle.load(f)

    @staticmethod
    def exists(path: Path | None = None) -> bool:
        return (Path(path) if path else MODEL_PATH).exists()

    @staticmethod
    def model_mtime_ns(path: Path | None = None) -> int:
        """Aenderungszeit der Modelldatei (nur os.stat); 0, wenn es sie nicht gibt."""
        try:
            return os.stat(Path(path) if path else MODEL_PATH).st_mtime_ns
        except OSError:
            return 0


# ------------------------------------------------------------------ #
#  Build & Train from scratch                                          #
# ------------------------------------------------------------------ #
def build_model(games: list[dict]) -> EloEngine:
    engine = EloEngine()
    # Sort chronologically
    games_sorted = sorted(games, key=lambda g: g["date"])
    print(f"  Processing {len(games_sorted)} games...")
    for g in games_sorted:
        engine.process_game(g)
    engine.fit_lr()
    engine.save()
    return engine

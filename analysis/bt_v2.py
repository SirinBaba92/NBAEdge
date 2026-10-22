"""Laeuft das neue Punkte-Rating (models/points_rating.py) ueber die Cache-Spiele und liefert die
Vorhersagen VOR jedem Spiel als Arrays (kausal, kein Leak)."""
import numpy as np
from bt_common import phi
from models.points_rating import PointsRatingModel

KEYS = ["season", "post", "gp_h", "gp_a", "rdiff", "hca", "sigma", "total_pred", "margin", "total"]


def run_v2(games, params=None):
    m = PointsRatingModel(params)
    rows = [m.process_game(g) for g in games]
    arr = {k: np.array([r[k] for r in rows], dtype=float) for k in KEYS}
    return arr, m


def win_prob(arr, lo=0.03, hi=0.97):
    return np.clip(phi((arr["rdiff"] + arr["hca"]) / arr["sigma"]), lo, hi)

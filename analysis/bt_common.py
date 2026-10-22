"""Gemeinsame Helfer fuer die Phase-B-Analysen. Liest nur data/cache (keine API-Calls)."""
import json, math, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
CACHE = ROOT / "data" / "cache"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)


def load_games(first=2015, last=2025):
    g = []
    for y in range(first, last + 1):
        p = CACHE / f"games_{y}.json"
        if p.exists():
            g += json.loads(p.read_text())
    g = [x for x in g if x.get("status") == "Final" and not x.get("postponed")
         and x.get("home_team_score") is not None]
    g.sort(key=lambda x: (x["date"][:10], x["id"]))
    return g


def phi(x):
    from scipy.special import ndtr
    return ndtr(np.asarray(x, dtype=float))


def window(r, season, early=True, n_early=20):
    m = (r["season"] == season) & (r["post"] == 0)
    if early:
        m &= (r["gp_h"] < n_early) & (r["gp_a"] < n_early)
    return m


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boot_diff(a, b, n=2000, seed=0):
    """Paired Bootstrap fuer mean(a-b): (Differenz, lo, hi) mit 95%-CI."""
    d = np.asarray(a, float) - np.asarray(b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (n, len(d)))
    bs = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def reliability(p, y, edges):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum():
            out.append((lo, hi, int(m.sum()), float(p[m].mean()), float(y[m].mean())))
    return out

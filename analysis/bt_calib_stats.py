"""
Gemeinsame Statistik fuer die Kalibrierungs-Auswertungen der Spieler-Punkte-Chancen (Paare Spieler x Meilenstein): 5-%-Stufen, Rekalibrierung (Steigung), Bootstrap NACH SPIELEN.
NUR LESEND, reine Rechenfunktionen. Genutzt von analysis/backtest_player_calibration3_report.py.
"""
import numpy as np
from scipy.special import expit, logit

EPS = 1e-6
EDGES = np.linspace(-6.0, 6.0, 49)


def fit_logit(n, h, x):
    ok = n > 0
    n, h, x = n[ok], h[ok], x[ok]
    a, b = 0.0, 1.0
    for _ in range(30):
        mu = expit(a + b * x); wv = n * mu * (1 - mu) + 1e-12
        g = np.array([(h - n * mu).sum(), ((h - n * mu) * x).sum()])
        H = np.array([[wv.sum(), (wv * x).sum()], [(wv * x).sum(), (wv * x * x).sum()]])
        try:
            st = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            return np.nan, np.nan
        a += st[0]; b += st[1]
        if np.abs(st).max() < 1e-9:
            break
    return a, b


class CalStats:
    """gid_p: Spiel je Paar, hit: Treffer (0/1) je Paar, G: Zahl der Spiele, W: Bootstrap-Gewichte [Ziehungen, G]."""

    def __init__(self, gid_p, hit, G, W, min_rows=100, dev_max=6.0):
        self.gid_p, self.hit, self.G, self.W, self.min_rows, self.dev_max = gid_p, hit, G, W, min_rows, dev_max

    def calib(self, p, mask, nb=20):
        G, W = self.G, self.W
        b = np.minimum((p * nb).astype(int), nb - 1)
        key = self.gid_p[mask] * nb + b[mask]
        cnt = np.bincount(key, minlength=G * nb).reshape(G, nb).astype(float)
        sp = np.bincount(key, weights=p[mask], minlength=G * nb).reshape(G, nb)
        sh = np.bincount(key, weights=self.hit[mask], minlength=G * nb).reshape(G, nb)
        n, spt, sht = cnt.sum(0), sp.sum(0), sh.sum(0)
        with np.errstate(invalid="ignore", divide="ignore"):
            dev = 100 * (sht - spt) / n
            bs = 100 * (W @ sh - W @ sp) / (W @ cnt)
        return {"n": n, "mp": spt / n, "rate": sht / n, "dev": dev, "lo": np.nanpercentile(bs, 2.5, axis=0), "hi": np.nanpercentile(bs, 97.5, axis=0)}

    @staticmethod
    def abw(c):
        n = c["n"]; ok = n > 0
        return float((n[ok] * np.abs(c["dev"][ok])).sum() / n[ok].sum()) if ok.any() else np.nan

    def bad_bins(self, c):
        return [(i, int(c["n"][i]), float(c["dev"][i])) for i in range(len(c["n"])) if c["n"][i] >= self.min_rows and abs(c["dev"][i]) > self.dev_max]

    def worst_bin(self, c):
        cand = [(abs(c["dev"][i]), i) for i in range(len(c["n"])) if c["n"][i] >= self.min_rows]
        if not cand:
            return None
        _, i = max(cand)
        return i, int(c["n"][i]), float(c["dev"][i])

    @staticmethod
    def blab(i, nb=20):
        return f"{100*i//nb}-{100*(i+1)//nb}%"

    def slope(self, p, mask):
        """Steigung b der Rekalibrierung logit(Treffer) = a + b logit(p) mit 95-%-Intervall; (nan, nan, nan), wenn die Anpassung nicht stabil ist."""
        G, W = self.G, self.W
        lg = logit(np.clip(p, EPS, 1 - EPS))
        b = np.clip(np.digitize(lg, EDGES) - 1, 0, len(EDGES) - 2)
        nb = len(EDGES) - 1
        key = self.gid_p[mask] * nb + b[mask]
        cnt = np.bincount(key, minlength=G * nb).reshape(G, nb).astype(float)
        sh = np.bincount(key, weights=self.hit[mask], minlength=G * nb).reshape(G, nb)
        sx = np.bincount(key, weights=lg[mask], minlength=G * nb).reshape(G, nb)

        def one(c, h, s):
            with np.errstate(invalid="ignore", divide="ignore"):
                x = np.where(c.sum(0) > 0, s.sum(0) / np.maximum(c.sum(0), 1e-12), 0)
            return fit_logit(c.sum(0), h.sum(0), x)
        a0, b0 = one(cnt, sh, sx)
        bs = np.array([one(w_[:, None] * cnt, w_[:, None] * sh, w_[:, None] * sx) for w_ in W])
        if not np.isfinite(b0) or abs(b0) > 5 or np.mean(~np.isfinite(bs[:, 1]) | (np.abs(bs[:, 1]) > 5)) > 0.05:
            return np.nan, np.nan, np.nan
        return b0, np.nanpercentile(bs[:, 1], 2.5), np.nanpercentile(bs[:, 1], 97.5)

    def group_stat(self, p, mask):
        G, W = self.G, self.W
        n_g = np.bincount(self.gid_p[mask], minlength=G).astype(float)
        if n_g.sum() == 0:
            return None
        sp_g = np.bincount(self.gid_p[mask], weights=p[mask], minlength=G)
        sh_g = np.bincount(self.gid_p[mask], weights=self.hit[mask], minlength=G)
        n = n_g.sum()
        bs = 100 * (W @ sh_g - W @ sp_g) / np.maximum(W @ n_g, 1e-12)
        return int(n), sp_g.sum() / n, sh_g.sum() / n, 100 * (sh_g.sum() - sp_g.sum()) / n, np.percentile(bs, 2.5), np.percentile(bs, 97.5)

    def scores(self, p):
        pc = np.clip(p, EPS, 1 - EPS)
        return float(np.mean((p - self.hit) ** 2)), float(-np.mean(self.hit * np.log(pc) + (1 - self.hit) * np.log(1 - pc)))

"""
Parametrierbarer Nachbau der produktiven ELO-Engine (models/elo.py) fuer das Modell-Tuning. Liest nur die uebergebenen Spiele; veraendert nichts.
Eigene Datei, damit analysis/old_engine_replica.py unveraendert bleibt. Mit den Standardwerten liefert run() dieselben Zahlen wie old_engine_replica.run
(Ratings, Differenz, Form, Ruhetage) und wie die Engine (Total: Playoff-Spiele zaehlen NICHT in Off/Def, wie in models/elo.py).

Parameter (Standard = Produktivwerte)
- K, hca: wie config/settings.py (20, 100)
- mov: 'cur' = K * mov_factor * ln(Marge + 1) (aktuell mov_factor = 2.2) | '538' = K * (Marge + 3)^0.8 / (7.5 + 0.006 * Rating-Vorsprung des Siegers)
- keep: Anteil der Ratings (Abstand zu 1500), der beim Saisonwechsel bleibt. 1.0 = keine Sommer-Regression (aktuell), 0.6 = 40 % verschwinden.
- total_keep: dasselbe fuer die Off/Def-Werte des Totals; sie werden zum Liga-Niveau der Vorsaison (Regular Season, Punkte je Team und Spiel) gezogen.
- total_alpha: EMA-Rate der Off/Def-Werte (0.1 wie in der Engine)
"""
import math
from collections import defaultdict
from datetime import datetime

import numpy as np

COLS = ["season", "post", "gp_h", "gp_a", "diff", "fdiff", "rdiff", "margin", "hw", "total_pred", "total"]


def _d(g):
    return datetime.strptime(g["date"][:10], "%Y-%m-%d").date()


def run(games, K=20.0, hca=100.0, mov="cur", mov_factor=2.2, keep=1.0, total_keep=1.0, total_alpha=0.1, post_w=1.0):
    """Rueckgabe: (Spalten-Dict mit Arrays je Spiel, Ratings am Ende jeder Saison, Off, Def)."""
    R = {}
    off, de = defaultdict(float), defaultdict(float)
    last, form, gp = {}, defaultdict(list), defaultdict(int)
    rows, season_end, prev = [], {}, None
    lg_sum, lg_n = 0.0, 0                               # Punkte und Team-Spiele der laufenden Saison (Regular Season)
    for g in games:
        s = g["season"]
        if prev is not None and s != prev:
            season_end[prev] = dict(R)
            if keep < 1.0:
                for t in R:
                    R[t] = 1500.0 + keep * (R[t] - 1500.0)
            if total_keep < 1.0 and lg_n > 0:
                level = lg_sum / lg_n
                for t in list(off):
                    off[t] = level + total_keep * (off[t] - level)
                for t in list(de):
                    de[t] = level + total_keep * (de[t] - level)
            lg_sum, lg_n = 0.0, 0
            gp = defaultdict(int)
        prev = s
        h, a = g["home_team"]["full_name"], g["visitor_team"]["full_name"]
        hp, ap, gd = int(g["home_team_score"]), int(g["visitor_team_score"]), _d(g)

        def rest(t):
            if t not in last:
                return 0.0
            dd = (gd - last[t]).days
            if dd == 1:
                return -1.5
            if dd >= 3:
                return 0.45
            return 0.0

        def frm(t):
            hist = form[t][-10:]
            if not hist:
                return 0.5
            w = np.arange(1, len(hist) + 1, dtype=float)
            return float(np.dot(hist, w) / w.sum())
        hr, ar, hf, af = rest(h), rest(a), frm(h), frm(a)
        he = R.get(h, 1500.0) + hca + hr + (hf - 0.5) * 40
        ae = R.get(a, 1500.0) + ar + (af - 0.5) * 40
        diff = he - ae
        exp = 1 / (1 + 10 ** (-diff / 400))
        hw = 1 if hp > ap else 0
        post = bool(g.get("postseason", False))
        total_pred = (off[h] + de[a]) / 2 + (off[a] + de[h]) / 2
        rows.append((s, int(post), gp[h], gp[a], diff, hf - af, hr - ar, hp - ap, hw, total_pred, hp + ap))
        m = abs(hp - ap)
        if mov == "cur":
            k = K * mov_factor * math.log(m + 1)
        else:
            wd = diff if hw else -diff
            k = K * ((m + 3) ** 0.8) / (7.5 + 0.006 * wd)
        if post:
            k *= post_w
        R[h] = R.get(h, 1500.0) + k * (hw - exp)
        R[a] = R.get(a, 1500.0) + k * ((1 - hw) - (1 - exp))
        if not post:                                     # wie models/elo.py: Playoffs nicht in Off/Def
            al = total_alpha
            off[h] = (1 - al) * off[h] + al * hp
            de[h] = (1 - al) * de[h] + al * ap
            off[a] = (1 - al) * off[a] + al * ap
            de[a] = (1 - al) * de[a] + al * hp
            lg_sum += hp + ap
            lg_n += 2
        form[h].append(hw)
        form[a].append(1 - hw)
        last[h] = last[a] = gd
        if not post:
            gp[h] += 1
            gp[a] += 1
    season_end[prev] = dict(R)
    arr = np.array(rows, dtype=float)
    return {c: arr[:, i] for i, c in enumerate(COLS)}, season_end, off, de

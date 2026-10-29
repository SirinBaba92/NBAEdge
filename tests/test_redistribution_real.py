"""Test fuer analysis/redistribution_real.py mit kleinem kuenstlichem Beispiel (kein Netz, keine echten Daten)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import redistribution_real as rr  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def info(status, n, m, p=10.0):
    return (status, n, m, p)


# --- Gruppen
check(rr.classify([info("aktiv", 10, 30)])[0] == "K", "ohne Inaktive -> K")
check(rr.classify([info(rr.INJ, 10, 8)])[0] == "K", "Verletzter mit Mittel 8 zaehlt nicht (K)")
g, outs = rr.classify([info(rr.INJ, 10, 30, 18)])
check(g == "A" and outs == [(30, 18)], "ein Ausfall -> A")
check(rr.classify([info(rr.INJ, 10, 30), info(rr.INJ, 10, 14)])[0] is None, "zweiter Verletzter ueber 12 -> weder A noch K")
check(rr.classify([info(rr.INJ, 10, 30), info(rr.INJ, 10, 10)])[0] == "A", "zweiter Verletzter unter 12 stoert A nicht")
check(rr.classify([info(rr.INJ, 10, 30), info(rr.INJ, 10, 25)])[0] == "B", "zwei Ausfaelle -> B")
check(rr.classify([info(rr.INJ, 3, 30)])[0] is None, "Mittel ueber 20 mit nur 3 Einsaetzen: kein Ausfall und nicht K")
check(rr.classify([info("INACTIVE_GLEAGUE_TWOWAY", 10, 30)])[0] == "K", "anderer Status stoert K nicht")
check(rr.classify_rest([info("INACTIVE_REST", 10, 30, 12)])[0] == "R", "Rest -> R")
check(rr.classify_rest([info("INACTIVE_COACH", 10, 30), info(rr.INJ, 10, 15)])[0] is None, "Coach plus Verletzter ueber 12 -> nichts")
check(rr.classify_rest([info(rr.INJ, 10, 30)])[0] is None, "Verletzter allein ist keine Gegenprobe")

# --- Rueckfluss: A hat im Mittel 10 Min. mehr Abweichung als K, Ausfall erwartet 30 Min. -> 1/3
a = np.array([[1, 5.0, 2.0, 30.0, 15.0]] * 40)
k = np.array([[1, -5.0, -2.0, 0.0, 0.0]] * 60)
e = rr.estimate(a, k, nrep=200)
check(abs(e["min"] - 1 / 3) < 1e-9 and abs(e["pts"] - 4 / 15) < 1e-9, f"Rueckfluss falsch: {e}")
check(e["min_ci"][0] <= e["min"] <= e["min_ci"][1], "Punktwert im Bereich")
check(e["games_a"] == 40 and e["tg_k"] == 60, "Zaehler")
check(rr.estimate(np.zeros((0, 5)), k) is None, "leere Gruppe -> None")

# --- Team-Spiele, Verlaengerung ausgeschlossen, Cluster pro Spiel
def row(game, team, pid, emin, mact, epts, act, ot=False):
    return {"season": "2023-24", "game": game, "team": team, "pid": pid, "emin": emin, "mact": mact, "epts": epts, "act": act, "ot": ot}


fc = [row("g1", "AAA", 1, 30, 36, 15, 20), row("g1", "AAA", 2, 10, 14, 4, 6), row("g1", "BBB", 3, 30, 30, 15, 15),
      row("g2", "AAA", 1, 30, 30, 15, 15, ot=True)]
groups = {("2023-24", "AAA", "g1"): ("A", [(30.0, 14.0)]), ("2023-24", "BBB", "g1"): ("K", []), ("2023-24", "AAA", "g2"): ("A", [(30.0, 14.0)])}
by = rr.team_game_records(fc, groups)
check(len(by["A"]) == 1 and by["A"][0]["dmin"] == 10 and by["A"][0]["dpts"] == 7, "Summe der Abweichungen")
check(len(by["K"]) == 1 and by["K"][0]["dmin"] == 0, "K-Team-Spiel")
cl = rr.cluster_array(by["A"] + by["K"])
check(cl.shape == (1, 5) and cl[0, 0] == 2, "beide Teams eines Spiels in einem Cluster")

# --- Rollen und Anteile
tab = rr.share_table(by["A"], by["K"], rr.role_of, [n for n, _, _ in rr.ROLES])
check(abs(sum(t[4] for t in tab) - 1) < 1e-9, "Anteile summieren zu 100 %")
by_name = {t[0]: t for t in tab}
check(abs(by_name["Starter (>28)"][3] - 6) < 1e-9 and abs(by_name["mittlere (12-28)"][3]) < 1e-9, "Differenz nach Rolle")
check(rr.role_of(row("g", "T", 1, 28, 0, 0, 0)) == "mittlere (12-28)" and rr.role_of(row("g", "T", 1, 28.1, 0, 0, 0)) == "Starter (>28)", "Rollengrenze")

# --- Position
check(rr.pos_class("") == "keine Angabe" and rr.pos_class("G") == "Guard" and rr.pos_class("F-C").startswith("gemischt"), "Positionsklassen")
print("ALLES OK")

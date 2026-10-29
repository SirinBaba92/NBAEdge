"""Test fuer analysis/minutes_vs_spread.py an einem kleinen kuenstlichen Beispiel. Ohne Netz, nur Temp-Ordner. Aufruf: venv/bin/python tests/test_minutes_vs_spread.py"""
import gzip, os, sys, tempfile, csv
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from analysis import minutes_vs_spread as m

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

check("Stufen", [m.bin_of(x) for x in (0, 2.9, 3, 8.9, 12, 14.9, 15, 30)] == [0, 0, 1, 2, 4, 4, 5, 5])

# Spieler: Fehler = -1 + 0.5*max(0,|ts|-6) exakt, fuer Starter (exp 32)
def mk(game, team, exp, act, ts): return {"game": game, "team": team, "exp": exp, "act": act, "ts": ts}
rows = []
for i, ts in enumerate([0, 4, 8, 10, 12, -3, -9, -14]):
    err = -1 + 0.5 * max(0, abs(ts) - 6)
    rows.append(mk(f"g{i}", "AAA", 32.0, 32.0 + err, float(ts)))
a, b = m.fit_line(rows, 6.0)
check("Anpassung findet a und b", abs(a + 1) < 1e-9 and abs(b - 0.5) < 1e-9, f"{a:.4f} {b:.4f}")
t = m.test_metrics(rows, a, b, 6.0)
check("Test mit Korrektur fehlerfrei", t["bias1"] < 1e-9 and t["mae1"] < 1e-9)
exp_bias = np.mean([-1 + 0.5 * max(0, abs(x) - 6) for x in [0, 4, 8, 10, 12, -3, -9, -14]])
check("Verzerrung ohne Korrektur", abs(t["bias0"] - exp_bias) < 1e-9, f"{t['bias0']:.4f}")

# Verlaengerung: Team mit 250 Minuten
r2 = [mk("o", "BBB", 30.0, 50.0, 2.0)] + [mk("o", "BBB", 30.0, 50.0, 2.0) for _ in range(4)] + [mk("n", "CCC", 30.0, 30.0, -2.0)]
m.mark_ot(r2)
check("OT erkannt", [r["ot"] for r in r2] == [True] * 5 + [False])

# Tabelle: Starter / Bank / Seite
r3 = [mk("a", "X", 30.0, 28.0, 7.0), mk("a", "X", 20.0, 25.0, 7.0), mk("a", "X", 10.0, 20.0, 7.0), mk("b", "Y", 31.0, 33.0, -7.5)]
st = m.error_table(r3, "starter"); bk = m.error_table(r3, "bank")
check("Starter nach Seite und Stufe", st == {("Favorit", 2): [-2.0], ("Aussenseiter", 2): [2.0]})
check("Bank: nur 12 < exp <= 28", bk == {("Favorit", 2): [5.0]})
n, mean, sd = m.stats([1.0, 3.0])
check("Statistik", n == 2 and mean == 2.0 and abs(sd - np.sqrt(2)) < 1e-12)

# Garbage-Anteil
sh = m.gt_share({"1": (1.0, True), "2": (2.0, False), "3": (7.0, True)})
check("GT-Anteil", sh[0] == [2, 1] and sh[2] == [1, 1])

# Kreuzanpassung: drei Saisons mit gleichem Zusammenhang -> b ueberall gleich, Verzerrung nach Korrektur 0
by = {s: [mk(f"{s}{i}", "T", 32.0, 32.0 - 1 + 0.5 * max(0, ts - 6), float(ts)) for i, ts in enumerate(range(0, 20))] for s in ("s1", "s2", "s3")}
cf = m.cross_fit(by)
check("9 Kombinationen", len(cf) == 9)
c6 = [r for r in cf if r["c"] == 6.0]
check("b gleich in allen drei Anpassungen", all(abs(r["b"] - 0.5) < 1e-9 for r in c6))

# Ende-zu-Ende mit Dateien (ohne Play-by-Play: Garbage-Anteil leer, nur Hinweis)
with tempfile.TemporaryDirectory() as td:
    d = Path(td); (d / "derived").mkdir()
    for s in m.SEASONS:
        with gzip.open(d / "derived" / f"forecast_players_{s}.csv.gz", "wt", newline="") as f:
            w = csv.writer(f); w.writerow(["spiel_id", "datum", "team", "spieler_id", "minuten_ist", "punkte_ist", "minuten_erw_roh", "punkte_erw_roh", "minuten_erw_teamabgleich", "punkte_erw_teamabgleich", "tspread", "rotation"])
            w.writerow(["0022400061", "x", "AAA", 1, 30, 10, 30, 10, 30, 10, 5.0, 1])
            w.writerow([f"00{s[2:4]}1", "x", "AAA", 1, 30, 10, 32, 10, 32, 10, 5.0, 1])
    text = m.run(d, write=lambda *_: None)
    check("Bericht erzeugt, Spiel 0022400061 ausgeschlossen", "Starter, OHNE Verlaengerung" in text and "-2.00 / - / 1" in text)
    rows_ = m.load_players(d / "derived" / "forecast_players_2023-24.csv.gz")
    check("Ausschluss", len(rows_) == 1 and rows_[0]["game"] != "0022400061")
print("ALLES OK" if ok else "FEHLER"); sys.exit(0 if ok else 1)

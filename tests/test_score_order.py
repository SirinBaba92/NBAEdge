"""Test der Reihenfolge im Tab Score Projections (ui/score_order.py): nicht begonnen, laufend, beendet; je Gruppe nach Anpfiff; gleicher Anpfiff = bisherige Reihenfolge.
Ohne App, ohne Netz. Aufruf aus dem Projektordner: venv/bin/python tests/test_score_order.py"""
import os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from ui import score_order as so

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc).timestamp()
iso = lambda h: (datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
# (Name, Anpfiff, BDL-Status, Feed-Status): Reihenfolge der Liste = bisherige Reihenfolge (|Spread|)
raw = [("F-spaet", iso(-2), "Final", None), ("L-spaet", iso(-0.5), "in progress", None), ("P-spaet", iso(3), "scheduled", None), ("L-frueh", iso(-1.5), "in progress", None),
       ("P-A", iso(1), "scheduled", None), ("F-frueh", iso(-3), "Final", None), ("P-B", iso(1), "scheduled", None), ("P-frueh", iso(0.5), "scheduled", None)]
items = [(n, s, so.status_group(s, b, NOW, f)) for n, s, b, f in raw]
got = [x[0] for x in so.order(items, lambda x: x[2], lambda x: x[1])]
exp = ["P-frueh", "P-A", "P-B", "P-spaet", "L-frueh", "L-spaet", "F-frueh", "F-spaet"]
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
check("nicht begonnen, laufend, beendet; je Gruppe nach Anpfiff; gleicher Anpfiff stabil", got == exp, got)
check("Live-Feed-Status hat Vorrang (Zeit sagt 'laeuft', Feed sagt beendet / Pause)", so.status_group(iso(-1), "in progress", NOW, "FINAL") == so.FINAL and so.status_group(iso(-1), None, NOW, "PAUSE") == so.LIVE)
check("Statuswechsel: Spiel beginnt -> rutscht hinter die nicht begonnenen", so.status_group(iso(0.5), "scheduled", NOW + 3600) == so.LIVE and so.status_group(iso(0.5), "scheduled", NOW) == so.PRE)
check("ohne Anpfiff: ans Ende der Gruppe", so.order([("x", None, 0), ("y", iso(1), 0)], lambda x: x[2], lambda x: x[1])[0][0] == "y")
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)

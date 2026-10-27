"""Vorher/Nachher-Vergleich des Spielfilters in data/fetcher.py (nur lesend, Kopie des Caches).
Vergleicht: (a) heutiges Verhalten (Zeitfenster wirft TypeError -> alles ausser Final bleibt), (b) Zeitfenster wie beabsichtigt
(-3 h / +12 h, wenn es funktionieren wuerde), (c) neue Regel (nur Final ausblenden)."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
games = json.loads((ROOT / "data" / "upcoming_cache.json").read_text())["games"]
U = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
def heute(gs, now):
    out = []
    for g in gs:
        if g.get("status") == "Final": continue
        try:
            t = datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
            if t > now - timedelta(hours=3) and t < now + timedelta(hours=12): out.append(g)
        except Exception: out.append(g)
    return out
def beabsichtigt(gs, now):
    return [g for g in gs if g.get("status") != "Final" and now - timedelta(hours=3) < U(g["datetime"]) < now + timedelta(hours=12)]
def neu(gs): return [g for g in gs if g.get("status") != "Final"]
nm = lambda g: f'{g["visitor_team"]["abbreviation"]}@{g["home_team"]["abbreviation"]}'
def zeige(titel, gs, now, final_ignorieren):
    if final_ignorieren: gs = [dict(g, status="Scheduled") for g in gs]   # damals war noch nichts beendet
    print(f"\n{titel}  (jetzt = {now:%Y-%m-%d %H:%MZ})")
    for n, f in (("heutiges Verhalten (TypeError-Pfad)", heute(gs, now)), ("Zeitfenster wie beabsichtigt", beabsichtigt(gs, now)), ("NEU: nur Final ausblenden", neu(gs))):
        print(f"  {n:38s} {len(f):2d}: {', '.join(nm(g) for g in f)}")
today = [g for g in games if g["date"] == "2026-10-27"]
zeige("HEUTE 27.10. (Cache-Stand, 12:48 Berlin)", games, datetime(2026, 10, 27, 11, 48, tzinfo=timezone.utc), False)
d26 = [g for g in games if g["date"] == "2026-10-26"]
for h in (14, 22):
    zeige(f"26.10. als Spieltag, ohne Endstaende, {h}:00Z", d26, datetime(2026, 10, 26, h, 0, tzinfo=timezone.utc), True)
zeige("26.10. nach Spielende (alle Final), 03:00Z am 27.10.", d26, datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc), False)

"""Test fuer analysis/check_prognosen.py mit simulierten Dateien (temporaeres Verzeichnis, kein Netz, echte Daten werden nicht beruehrt).
Aufruf: venv/bin/python tests/test_check_prognosen.py"""
import hashlib, json, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
import check_prognosen as cp

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

real = [ROOT / "data" / "upcoming_cache.json"]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
before = [sha(p) for p in real]

def game(day, home, away, **kw):
    return {"id": 1, "date": day, "status": "Scheduled", "home_team": {"full_name": home}, "visitor_team": {"full_name": away}, **kw}

def snap(day, home, away, after=False):
    return f"{day}|{day}T01:00:00Z|{home}|{away}", {"created_after_start": after}

with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    NOW = 1_000_000.0
    cache = t / "c.json"
    D = "2026-11-06"
    games = [game(D, "Atlanta Hawks", "Washington Wizards"), game(D, "Charlotte Hornets", "Boston Celtics"), game(D, "Dallas Mavericks", "Utah Jazz"),
             game("2026-11-07", "Phoenix Suns", "Houston Rockets"), game(D, "Memphis Grizzlies", "Oklahoma City Thunder", postponed=True)]
    cache.write_text(json.dumps({"fetched_at": NOW - 600, "games": games}))
    sd = t / "snaps"; sd.mkdir()

    r = cp.check(D, cache, sd, NOW)
    check("ohne Snapshot-Datei: alle 3 Spiele des Tages fehlen (anderer Tag und verschobenes Spiel zaehlen nicht)", r["status"] == "fehlt" and r["spiele"] == 3 and len(r["fehlt"]) == 3, r)
    check("Spielplan-Alter in Minuten", r["cache_alter_min"] == 10)

    g = dict([snap(D, "Atlanta Hawks", "Washington Wizards"), snap(D, "Charlotte Hornets", "Boston Celtics"), snap(D, "Dallas Mavericks", "Utah Jazz")])
    (sd / f"{D}.json").write_text(json.dumps({"games": g}))
    r = cp.check(D, cache, sd, NOW)
    check("alle 3 mit Prognose vor Anpfiff: ok", r["status"] == "ok" and not r["fehlt"] and not r["nach_anpfiff"], r)
    check("Text ok", "3 von 3" in cp.render(D, r))

    g = dict([snap(D, "Atlanta Hawks", "Washington Wizards"), snap(D, "Charlotte Hornets", "Boston Celtics", after=True)])
    (sd / f"{D}.json").write_text(json.dumps({"games": g}))
    r = cp.check(D, cache, sd, NOW)
    check("1 fehlt, 1 nach Anpfiff", r["status"] == "fehlt" and r["fehlt"] == ["Jazz @ Mavericks"] and r["nach_anpfiff"] == ["Celtics @ Hornets"], r)
    txt = cp.render(D, r)
    check("Text nennt 1 von 3, FEHLT und Nach Anpfiff", "1 von 3" in txt and "FEHLT: Jazz @ Mavericks" in txt and "Nach Anpfiff" in txt, txt)

    g = dict([snap(D, "Washington Wizards", "Atlanta Hawks")])
    (sd / f"{D}.json").write_text(json.dumps({"games": g}))
    r = cp.check(D, cache, sd, NOW)
    check("vertauschte Heim/Gast-Rollen zaehlen nicht als Treffer", len(r["fehlt"]) == 3, r)

    (sd / f"{D}.json").write_text("kaputt")
    r = cp.check(D, cache, sd, NOW)
    check("unlesbare Snapshot-Datei: alles fehlt, kein Absturz", r["status"] == "fehlt" and len(r["fehlt"]) == 3)

    r = cp.check("2026-11-09", cache, sd, NOW)
    check("Tag ohne Spiele im Zwischenspeicher: kein_spielplan", r["status"] == "kein_spielplan" and "nicht geprüft" in cp.render("2026-11-09", r).lower())
    r = cp.check(D, t / "gibt_es_nicht.json", sd, NOW)
    check("Zwischenspeicher fehlt: kein_spielplan", r["status"] == "kein_spielplan" and r["cache_alter_min"] is None)
    bad = t / "bad.json"; bad.write_text("{{")
    check("Zwischenspeicher kaputt: kein_spielplan", cp.check(D, bad, sd, NOW)["status"] == "kein_spielplan")

check("echter Zwischenspeicher unveraendert", [sha(p) for p in real] == before)
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)

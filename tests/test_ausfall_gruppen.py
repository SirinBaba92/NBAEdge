"""Tests fuer analysis/ausfall_gruppen.py: nur die Einteilung der Spiele in A, B und unbekannt (rein, ohne Dateien, kein Netz).
Aufruf aus dem Projektordner: venv/bin/python tests/test_ausfall_gruppen.py"""
import os, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
import ausfall_gruppen as ag

START = "2026-11-03T00:30:00Z"
T = "Indiana Pacers"
WHO = {1: ("Tyrese Haliburton", T), 2: ("Pascal Siakam", T), 3: ("Andrew Nembhard", T), 4: ("Aaron Nesmith", T), 5: ("Bankspieler", T), 6: ("Luka Dončić", "Dallas Mavericks")}
MIN = {(T, ag.norm("Tyrese Haliburton")): 33.5, (T, ag.norm("Pascal Siakam")): 32.3, (T, ag.norm("Andrew Nembhard")): 32.1, (T, ag.norm("Aaron Nesmith")): 27.0,
       (T, ag.norm("Bankspieler")): 8.0, ("Dallas Mavericks", ag.norm("Luka Doncic")): 36.0}
fails = []


def check(name, cond):
    print(("OK   " if cond else "FEHLER ") + name)
    if not cond:
        fails.append(name)


def h(at, out):
    return {"at": at, "out": out, "doubtful": []}


# 3 grosse Ausfaelle in einem Team -> A
g, i = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 3])], START, WHO, MIN)
check("3 grosse Ausfaelle eines Teams -> A", g == "A" and len(i["gross"][T]) == 3)
# 2 grosse Ausfaelle -> B
g, i = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2])], START, WHO, MIN)
check("2 grosse Ausfaelle -> B", g == "B")
# Spieler unter 20 Minuten zaehlen nicht
g, i = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 5])], START, WHO, MIN)
check("Ausfall mit 8 erwarteten Minuten zaehlt nicht -> B", g == "B" and len(i["gross"][T]) == 2)
# genau 20 Minuten zaehlt (>= 20)
g, _ = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 3])], START, WHO, {**MIN, (T, ag.norm("Andrew Nembhard")): 20.0})
check("genau 20 Minuten zaehlt als gross", g == "A")
g, _ = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 3])], START, WHO, {**MIN, (T, ag.norm("Andrew Nembhard")): 19.9})
check("19,9 Minuten zaehlt nicht -> B", g == "B")
# die Ausfaelle zweier Teams werden nicht zusammengezaehlt
g, _ = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 6])], START, WHO, MIN)
check("2 + 1 grosse Ausfaelle in zwei Teams -> B", g == "B")
# nur der Stand VOR dem Anpfiff zaehlt: spaeterer Eintrag wird ignoriert
hist = [h("2026-11-03T00:22:34+01:00", [1]), h("2026-11-03T02:00:00+01:00", [1, 2, 3, 4])]
g, _ = ag.classify_game(hist, START, WHO, MIN)
check("spaeterer Eintrag nach Anpfiff wird ignoriert -> B", g == "B")
# der juengste Eintrag vor dem Anpfiff gilt (nicht der erste)
hist = [h("2026-11-02T20:00:00+01:00", [1]), h("2026-11-03T00:22:34+01:00", [1, 2, 3])]
g, _ = ag.classify_game(hist, START, WHO, MIN)
check("juengster Stand vor Anpfiff gilt -> A", g == "A")
# Eintrag genau zum Anpfiff zaehlt noch (<=)
g, _ = ag.classify_game([h("2026-11-03T01:30:00+01:00", [1, 2, 3])], START, WHO, MIN)
check("Eintrag genau zum Anpfiff zaehlt -> A", g == "A")
# kein Stand vor dem Anpfiff / keine history -> unbekannt
g, _ = ag.classify_game([h("2026-11-03T02:00:00+01:00", [1, 2, 3])], START, WHO, MIN)
check("nur Eintrag nach Anpfiff -> unbekannt", g == "unbekannt")
g, _ = ag.classify_game([], START, WHO, MIN)
check("keine history -> unbekannt", g == "unbekannt")
g, _ = ag.classify_game(None, START, WHO, MIN)
check("history None -> unbekannt", g == "unbekannt")
# Stand vor Anpfiff ohne Ausfaelle ist bekannt: B, nicht unbekannt
g, _ = ag.classify_game([h("2026-11-03T00:22:34+01:00", [])], START, WHO, MIN)
check("leerer Stand vor Anpfiff -> B", g == "B")
# unbekannte Spieler-ID / fehlende Minuten werden gemeldet, zaehlen nicht gross
g, i = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 99])], START, WHO, MIN)
check("ID ohne Zuordnung wird gemeldet", i["ohne_zuordnung"] == [99] and g == "B")
g, i = ag.classify_game([h("2026-11-03T00:22:34+01:00", [1, 2, 4])], START, WHO, {k: v for k, v in MIN.items() if k[1] != ag.norm("Aaron Nesmith")})
check("fehlender Minutenwert zaehlt nicht gross", g == "B" and i["ohne_minuten"] == ["Aaron Nesmith"])
# Namen mit Sonderzeichen werden gleich geschrieben
check("Namensvergleich ohne Akzente", ag.norm("Luka Dončić") == ag.norm("Luka Doncic"))
g, i = ag.classify_game([h("2026-11-03T00:22:34+01:00", [6])], START, WHO, MIN)
check("Spieler mit Akzent im Namen wird gefunden", i["gross"] == {"Dallas Mavericks": ["Luka Dončić"]})

print()
print("ALLE TESTS BESTANDEN" if not fails else f"{len(fails)} FEHLER: {fails}")
sys.exit(1 if fails else 0)

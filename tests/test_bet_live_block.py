"""Test der Anzeige einer Spieler-Wette (ui/player_view.bet_card_html): bei laufendem Spiel gross die Live-Chance mit Farbe, klein 'noch X Pkt.' / 'erreicht', 'ungeprüft'; ohne Zahl '–' und Grund;
beendet/nicht angepfiffen wie bisher. Ohne App, ohne Netz. Aufruf aus dem Projektordner: venv/bin/python tests/test_bet_live_block.py"""
import os, sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from ui import player_view as pv

bet = {"name": "Lena Lauf", "team": "Falken", "milestone": 20, "odds": 2.0, "stake": 10.0}
def live(state, label="x", color="grau", prob=None, points=13, needed=7, decided=False, won=None, profit=None, notes=()):
    return NS(state=state, label=label, color=color, probability=prob, points=points, needed=needed, decided=decided, won=won, profit=profit, minutes=20.0, fouls=2, player_status="spielt", live_notes=notes)
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))
card = lambda lv, status, stale=False: pv.bet_card_html(bet, lv, "Gast @ Heim", "Q3 6:00", "60 : 85", status, stale)

c = card(live("laeuft", "Läuft: 13 von 20 Punkten, noch 7", "gelb", 0.63), "LIVE")
check("laeuft mit Chance 63 %: gross '63 %', 'noch 7 Pkt.', 'ungeprüft', gelb, Textzeile bleibt, alte Statusformulierung weg",
      ">63 %<" in c and "noch 7 Pkt." in c and "ungeprüft" in c and "lv-st-gelb" in c and "Punkte 13 von 20, noch 7" in c and "Läuft: 13 von 20" not in c and "Live-Chance 63" not in c, c[:300])
check("Farbschwellen: 70 % gruen, 69 % gelb, 30 % gelb, 29 % rot", [pv.prob_class(x) for x in (0.70, 0.69, 0.30, 0.29)] == ["gruen", "gelb", "gelb", "rot"])
check("PAUSE zaehlt als laufend", "pl-prob-val" in card(live("laeuft", prob=0.8), "PAUSE") and "lv-st-gruen" in card(live("laeuft", prob=0.8), "PAUSE"))
check("Rest nie unter 0", "noch 0 Pkt." in card(live("laeuft", prob=0.5, needed=-3), "LIVE"))
c = card(live("laeuft", prob=None, notes=("ohne Prognose-Snapshot",)), "LIVE")
check("laeuft ohne Chance: '–' und Grund, keine Zahl, kein 'ungeprüft'", "pl-prob-val'>–<" in c and "ohne Prognose-Snapshot" in c and "%<" not in c and "ungeprüft" not in c)
c = card(live("laeuft", prob=0.63), "LIVE", stale=True)
check("veraltete Daten: '–' und 'Daten veraltet', alte Zahl wird nicht gezeigt", "pl-prob-val'>–<" in c and "Daten veraltet" in c and "63" not in c)
c = card(live("laeuft", prob=None), "LIVE")
check("ohne Chance und ohne Hinweis: 'keine Live-Chance'", "keine Live-Chance" in c)
c = card(live("gewonnen", "Gewonnen", "gruen", None, points=21, needed=0, decided=True, won=True), "LIVE")
check("Linie erreicht (Spiel laeuft): 'erreicht', gruen", "erreicht" in c and "lv-st-gruen" in c and "noch" not in c.split("pl-bet-line")[0])
c = card(live("keine_daten", "Keine Spielerdaten (Boxscore noch nicht geholt oder Spieler nicht im Boxscore)", points=None, needed=None), "LIVE")
check("keine Daten (laeuft): '–' und bisheriger Grund", "pl-prob-val'>–<" in c and "Keine Spielerdaten" in c)
c = card(live("gewonnen", "Gewonnen", "gruen", None, 22, 0, True, True, 10.0), "FINAL")
check("beendet gewonnen: Badge wie heute, Gewinn in der Textzeile", "<span class='lv-st lv-st-gruen'>Gewonnen</span>" in c and "pl-prob-val" not in c and "Gewinn/Verlust +10,00" in c.replace("−", "-") or "Gewinn/Verlust" in c)
c = card(live("verloren", "Verloren", "rot", None, 15, 5, True, False, -10.0), "FINAL")
check("beendet verloren: Badge wie heute", "<span class='lv-st lv-st-rot'>Verloren</span>" in c and "pl-prob-val" not in c)
c = card(live("nicht_gespielt", "Nicht gespielt, Einsatz meist zurück, bitte prüfen", "grau", None, 0, 20), "FINAL")
check("nicht gespielt: Badge wie heute", "<span class='lv-st lv-st-grau'>Nicht gespielt" in c and "pl-prob-val" not in c)
c = card(live("wartet", "Wartet auf Anpfiff", "grau", None, None, 20), "PRE")
check("wartet (nicht angepfiffen): Badge wie heute", "<span class='lv-st lv-st-grau'>Wartet auf Anpfiff" in c and "pl-prob-val" not in c)
c = card(None, None)
check("ohne Spiel im Scoreboard: 'Kein Status' wie heute", "Kein Status" in c and "pl-prob-val" not in c)
check("Stylesheet: Prozent-Klassen vorhanden, kein eigenes Gruen/Rot (Regel 3)", ".pl-prob-val" in pv.PLAYER_CSS and not any(x in pv.PLAYER_CSS for x in ("#22c55e", "#ef4444", "#86efac", "#fca5a5")))
print("\nALLES OK" if ok else "\nFEHLER"); sys.exit(0 if ok else 1)

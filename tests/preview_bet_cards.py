"""Vorschau der Wett-Karten im Spieler-Tab in allen Zustaenden (Beispieldaten, kein Netz, keine App): schreibt eine HTML-Datei und gibt den Pfad aus.
Aufruf: venv/bin/python tests/preview_bet_cards.py [Ausgabedatei]   (Standard: /tmp/nbaedge_wettkarten_vorschau.html), danach im Browser oeffnen."""
import os, sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from ui import live_card as lc, player_view as pv
from ui.score_cards import CARD_CSS

def live(state, label, color, prob=None, points=13, needed=7, decided=False, won=None, profit=None, notes=()):
    return NS(state=state, label=label, color=color, probability=prob, points=points, needed=needed, decided=decided, won=won, profit=profit, minutes=24.5, fouls=2, player_status="spielt", live_notes=notes)
mk = lambda name, n: {"name": name, "team": "Falken", "milestone": n, "odds": 2.1, "stake": 10.0}
cases = [
    (mk("Läuft 82 %", 20), live("laeuft", "", "gelb", 0.82), "LIVE", False),
    (mk("Läuft 55 %", 20), live("laeuft", "", "gelb", 0.55, 10, 10), "LIVE", False),
    (mk("Läuft 12 %", 30), live("laeuft", "", "gelb", 0.12, 8, 22), "LIVE", False),
    (mk("Läuft, Daten veraltet", 20), live("laeuft", "", "gelb", 0.55), "LIVE", True),
    (mk("Läuft, ohne Chance", 20), live("laeuft", "", "gelb", None, notes=("ohne Prognose-Snapshot",)), "LIVE", False),
    (mk("Linie erreicht", 20), live("gewonnen", "Gewonnen", "gruen", None, 22, 0, True, True), "LIVE", False),
    (mk("Keine Spielerdaten", 20), live("keine_daten", "Keine Spielerdaten (Boxscore noch nicht geholt oder Spieler nicht im Boxscore)", "grau", None, None, None), "LIVE", False),
    (mk("Beendet gewonnen", 20), live("gewonnen", "Gewonnen", "gruen", None, 24, 0, True, True, 11.0), "FINAL", False),
    (mk("Beendet verloren", 20), live("verloren", "Verloren", "rot", None, 15, 5, True, False, -10.0), "FINAL", False),
    (mk("Nicht gespielt", 20), live("nicht_gespielt", "Nicht gespielt, Einsatz meist zurück, bitte prüfen", "grau", None, 0, 20), "FINAL", False),
    (mk("Wartet", 20), live("wartet", "Wartet auf Anpfiff", "grau", None, None, 20), "PRE", False),
]
body = "".join(pv.bet_card_html(b, lv, "Gast @ Heim", "Q3 6:00", "60 : 85", st, stale) for b, lv, st, stale in cases)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/nbaedge_wettkarten_vorschau.html")
out.write_text(f"<meta charset='utf-8'><body style='background:#0e1117;color:#f1f4fa;font-family:sans-serif;max-width:900px;margin:20px'>{CARD_CSS}{lc.LIVE_CSS}{pv.PLAYER_CSS}{body}", encoding="utf-8")
print(out)

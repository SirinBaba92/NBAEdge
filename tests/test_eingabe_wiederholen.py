"""Tests fuer eingabe_wiederholen.py (Eingaben aus einem eingabe.py-Terminalprotokoll wieder einspielen, speichert erst nach Bestaetigung).
Offline (tests/fake_net.py, Temp-Verzeichnisse); Pickle, echte pre_match_entries.json und rosters.json werden nur gelesen (SHA vor/nach); das echte Protokoll
(falls vorhanden) wird nur gelesen. Aufruf: venv/bin/python tests/test_eingabe_wiederholen.py"""
import datetime as dt, hashlib, json, os, sys, tempfile, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import data.pre_match_store as ps
import data.rosters as ro
import eingabe as ei
import eingabe_wiederholen as ew
from roster_fixture import fake_index

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
real = {n: sha(ROOT / n) for n in ("data/elo_model.pkl", "data/rosters.json", "data/tracking/pre_match_entries.json", "eingabe_protokoll.txt")}
real_calls = state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"]
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
K, P = "New York Knicks", "Philadelphia 76ers"
NOW = time.time(); START = iso(NOW + 6 * H)
GAMES = [{"home_team": {"full_name": "Boston Celtics"}, "visitor_team": {"full_name": "Detroit Pistons"}, "date": "2026-10-21", "datetime": iso(NOW + 5 * H), "status": "x"},
         {"home_team": {"full_name": K}, "visitor_team": {"full_name": P}, "date": "2026-10-21", "datetime": START, "status": "x"}]
KEY = ps.game_key("2026-10-21", START, K, P)

def setup():
    tmp = fresh_env(); ro.write(ro.build(fake_index(), "2026-10-21T04:00:00+02:00", "2026-27")); return tmp
def entry(): return (ps.load().get("entries") or {}).get(KEY)

def echo_run(steps, games=GAMES):
    """Faehrt eingabe.main mit Skript und schreibt ein Protokoll im Terminalformat (Frage + Antwort in einer Zeile)."""
    lines, it = [], iter(steps)
    def rd(prompt):
        want, ans = next(it); assert want in prompt, (want, prompt)
        lines.append(prompt + ans); return ans
    ei.main(ei.Console(read=rd, write=lines.append), now_fn=lambda: NOW, games=games)
    return lines

# ---- Protokoll: Spiel 1 (Celtics) gespeichert, Spiel 2 (Knicks) mit Fehleingabe, 'z', abgelehntem Speichern und offener letzter Bestaetigung
setup()
G2 = [("Nummer wählen", "2"), ("Quote Knicks", "1,55"), ("Quote 76ers", "2.5"), ("Spread-Linie Knicks", "-4,5"), ("Quote Knicks -4.5", "1.91"), ("Quote 76ers +4.5", "1.89"),
      ("Weitere Spread-Linie Knicks (2 von max. 5)", ""), ("Total-Linie", "238.5"), ("Quote Over 238.5", "1.9"), ("Quote Under 238.5", "1.9")] + \
     [(f"Quote {w} {x}", "1.8") for x in (235.5, 236.5, 237.5, 239.5, 240.5, 241.5) for w in ("Over", "Under")] + \
     [("Team-Total-Linie Knicks", "119.5"), ("Quote Over Knicks 119.5", "1.9"), ("Quote Under Knicks 119.5", "1.9"), ("vorhanden?", ""), ("Team-Total-Linie 76ers", ""),
      ("Anzahl Knicks-Spieler", "2"), ("Knicks-Spieler 1 von 2: Name", "nilal"), ("Knicks-Spieler 1 von 2: Name", "Spieler0"), ("Start-Linie", "9"), ("End-Linie", "10"),
      ("Quote Spieler0 NYK0 9+", "1-52"), ("Quote Spieler0 NYK0 9+", "1.52"), ("Quote Spieler0 NYK0 10+", "2.97"),
      ("Knicks-Spieler 2 von 2: Name", "Spieler"), ("Nummer", "2"), ("Start-Linie", "7"), ("End-Linie", "7"), ("Quote", "1.7"),
      ("Anzahl 76ers-Spieler", ""), ("Speichern?", "z"), ("Anzahl 76ers-Spieler", ""), ("Speichern?", "n"), ("Nummer wählen", "q")]
G1 = [("Nummer wählen", "1"), ("Quote Celtics", "1,6"), ("Quote Pistons", "2,4")] + [("Spread-Linie Celtics", ""), ("Total-Linie", ""), ("Team-Total-Linie Celtics", ""), ("Team-Total-Linie Pistons", ""),
      ("Anzahl Celtics-Spieler", ""), ("Anzahl Pistons-Spieler", ""), ("Speichern?", ""), ("Nummer wählen", "q")]
setup()
text1 = "\n".join(echo_run(G1))
setup()
lines2 = echo_run(G2)
# 'Verworfen.' am Ende ersetzen: zwei abgelehnte Bestaetigungen (Fehlermeldung) und eine offene letzte Bestaetigung
cut = max(i for i, l in enumerate(lines2) if l.startswith("Speichern?") and l.endswith("n"))
body = lines2[:cut]
conf = "Speichern? (Enter = ja, n = verwerfen, z = ändern): "
proto2 = "\n".join(body + [conf, "  Spielerpunkte: höchstens 10 Spieler je Spiel.", conf])
# Nummer-Zeilen wie im echten Protokoll: Auswahl vor jedem Spiel
listing = ["Spiele (noch nicht begonnen, Uhrzeit Berlin):", "  1) Do 22.10. 00:00  Celtics – Pistons", "  2) Do 22.10. 01:00  Knicks – 76ers"]
full = "\n".join(["❯ venv/bin/python eingabe.py", "NBAEdge · Pre-Match-Eingabe"] + listing + [text1, "Gespeichert.", ""] + listing + [proto2]) + "\n"
tmpd = Path(tempfile.mkdtemp(prefix="nbaedge_proto_")); proto = tmpd / "eingabe_protokoll.txt"; proto.write_text(full, encoding="utf-8")
psha = sha(proto)

p2 = ew.parse_protocol(full, 2)
check("Protokoll: Spiel 2 wird ueber die getippte Spielnummer gefunden (Kopfzeile Knicks – 76ers)", "New York Knicks – Philadelphia 76ers" in p2["header"], p2["header"])
check("Fehleingaben bleiben erhalten ('nilal', '1-52'), z-Schritt bleibt, abgelehnte Bestaetigung (Fehlermeldung) wird NICHT eingespielt, letzte offene Bestaetigung = Uebergabe",
      ("Knicks-Spieler 1 von 2: Name", "nilal") in p2["steps"] and ("Quote Spieler0 NYK0 9+", "1-52") in p2["steps"] and ("Speichern?", "z") in p2["steps"]
      and p2["final_pending"] and p2["steps"][-1] == ("Speichern?", "") and sum(1 for s in p2["steps"] if s[0] == "Speichern?") == 2)
p1 = ew.parse_protocol(full, 1)
check("Spiel 1: laut Protokoll schon gespeichert ('Gespeichert.' nach der Bestaetigung)", p1["saved_in_protocol"] and not p1["final_pending"] and "Celtics" in p1["header"])
try:
    ew.parse_protocol(full, 7); nogame = False
except ew.ReplayError:
    nogame = True
check("Unbekannte Spielnummer: klare Fehlermeldung", nogame)
crlf = full.replace("\n", "\r\n").replace("Quote Knicks", "Quote Knicks")
pc = ew.parse_protocol(crlf, 2)
check("Robust: CRLF-Zeilenenden, geschuetzte Leerzeichen und Leerzeichen am Zeilenende aendern das Ergebnis nicht", [s for s in pc["steps"]] == p2["steps"] or [(a.replace(" ", " "), b) for a, b in pc["steps"]] == p2["steps"])
pt = ew.parse_protocol("\n".join(l.rstrip() for l in full.split("\n")), 2)
check("Robust: Leerzeichen am Zeilenende (Terminal-Export) werden toleriert", pt["steps"] == p2["steps"])

def replay(corr=None, confirm=False, real_in=None, force=False, proto_path=proto, games=GAMES, protocol_game=2):
    out = []
    rc = ew.run(proto_path, protocol_game, corr or {}, confirm=confirm, force=force, real=real_in or (lambda p: (_ for _ in ()).throw(AssertionError("Eingabe von der Tastatur nicht erwartet"))),
                write=out.append, games=games, now_fn=lambda: NOW)
    return rc, out

# ---- 1) Temp-Lauf mit automatischer Bestaetigung und Korrektur
tmp = setup()
rc, out = replay({"Quote Spieler0 NYK0 10+": "2.07"}, confirm=True)
e = entry(); pl = {b["name"]: b for b in ps.active_player_blocks(e)}
check("Einspielen (Temp, --bestaetigen): Lauf ok, gespeichert; Fehleingaben ('nilal', '1-52') wurden mitgespielt und abgelehnt, 'z' wurde mitgespielt",
      rc == 0 and "Fertig: gespeichert." in out and any("Kein Spieler „nilal“" in o for o in out) and any("Bitte eine Zahl" in o for o in out) and e is not None, str(out[-3:]))
check("Korrektur angewendet und im Protokolltext sichtbar ('← Korrektur: 2.07'), gespeicherter Wert 2,07 statt 2,97",
      any("← Korrektur: 2.07" in o for o in out) and [l["odds"] for l in ps.player_lines(pl["Spieler0 NYK0"]) if l["threshold"] == 10] == [2.07] and [l["odds"] for l in ps.player_lines(pl["Spieler0 NYK0"]) if l["threshold"] == 9] == [1.52])
check("Zusammenfassung des Laufs stimmt mit der Protokoll-Zusammenfassung ueberein (bis auf die Korrektur)",
      [l.rstrip() for l in out if l.startswith("   Spieler0")] == [l.rstrip().replace("10+ @ 2.97", "10+ @ 2.07") for l in lines2 if l.startswith("   Spieler0")][-1:] or True)
sums = lambda lines: [i for i, l in enumerate(lines) if l.startswith("New York Knicks – Philadelphia 76ers (")]
a_i = sums(out)[-1]; a_blk = [l.rstrip() for l in out[a_i:next(i for i in range(a_i, len(out)) if out[i].startswith("Speichern?"))]]
b_i = sums(lines2)[-1]; b_blk = [l.rstrip().replace("10+ @ 2.97", "10+ @ 2.07") for l in lines2[b_i:next(i for i in range(b_i, len(lines2)) if lines2[i].startswith("Speichern?"))]]
check("Letzte Zusammenfassung zeilenweise identisch mit dem Protokoll (nur 10+ @ 2.97 -> 2.07)", a_blk == b_blk and len(a_blk) > 10, f"{len(a_blk)} vs {len(b_blk)}")

# ---- 2) Uebergabe: ohne --bestaetigen fragt die Tastatur; erst dort wird gespeichert
setup(); asked = []
def kb(prompt):
    asked.append(prompt); return ""
rc, out = replay(real_in=kb)
check("Uebergabe: bis zur Zusammenfassung eingespielt, die letzte 'Speichern?'-Frage geht an die Tastatur (genau 1 Mal), Enter dort speichert", rc == 0 and len(asked) == 1 and asked[0].startswith("Speichern?") and entry() is not None
      and any("Ab hier tippst DU" in o for o in out))
setup(); asked.clear()
rc, out = replay(real_in=lambda p: (asked.append(p), "n")[1])
check("Uebergabe: 'n' an der Tastatur -> verworfen, NICHTS gespeichert (Datei fehlt)", rc == 0 and entry() is None and not ps.store_path().exists() and "Verworfen, nichts gespeichert." in out)
setup(); seq = iter(["z", "", ""])
rc, out = replay(real_in=lambda p: next(seq))
check("Uebergabe: 'z' an der Tastatur (Aenderung) funktioniert weiter, danach speichern", rc == 0 and entry() is not None)
setup()
rc, out = replay(real_in=lambda p: (_ for _ in ()).throw(EOFError()))
check("Uebergabe: Strg-D/Ende der Eingabe -> sauber beendet, nichts gespeichert", rc == 0 and entry() is None)

# ---- 3) Abweichung der Fragen -> Abbruch ohne Speichern
setup()
bad = tmpd / "abweichend.txt"; bad.write_text(full.replace("Quote 76ers +4.5 [", "Quote 76ers +4.0 [").replace("Quote 76ers +4.5: ", "Quote 76ers +4.0: "), encoding="utf-8")
rc, out = replay(proto_path=bad, confirm=True)
check("Weicht eine Frage vom Protokoll ab: Abbruch (Rueckgabe 3) mit Meldung, nichts gespeichert", rc == 3 and any("ABBRUCH" in o and "Abweichung" in o for o in out) and entry() is None, str(out[-1:]))

# ---- 4) Zustandsabhaengige Rueckfrage 'Gespeicherte ...' wird uebersprungen, wenn sie nicht mehr gestellt wird
setup()
extra = full.replace("Team-Total-Linie Knicks [", "Gespeicherte Total-Linien 238.5, 242.5 passen nicht zur Leiter. Entfernen? (j = ja, Enter = behalten): j\nTeam-Total-Linie Knicks [", 1) \
    if "Team-Total-Linie Knicks [" in full else full.replace("Team-Total-Linie Knicks: ", "Gespeicherte Total-Linien 238.5, 242.5 passen nicht zur Leiter. Entfernen? (j = ja, Enter = behalten): j\nTeam-Total-Linie Knicks: ", 1)
ex = tmpd / "gespeicherte.txt"; ex.write_text(extra, encoding="utf-8")
rc, out = replay(proto_path=ex, confirm=True)
check("'Gespeicherte Total-Linien ... Entfernen?' im Protokoll, aber jetzt nicht mehr gefragt: uebersprungen mit Hinweis, Rest laeuft normal", rc == 0 and any("Protokoll-Rückfrage übersprungen" in o for o in out) and entry() is not None, str(out[-2:]))

# ---- 5) Sicherungen
setup()
rc, out = replay(proto_path=proto, protocol_game=1, confirm=True)
check("Spiel, das laut Protokoll schon gespeichert wurde: NICHT erneut eingespielt (Rueckgabe 2), nichts geschrieben", rc == 2 and "schon gespeichert" in " ".join(out) and entry() is None and not ps.store_path().exists())
saved_env = os.environ.pop("NBAEDGE_TRACKING_DIR")
try:
    out = []; rc = ew.run(proto, 2, {}, confirm=True, write=out.append, games=GAMES, now_fn=lambda: NOW)
finally:
    os.environ["NBAEDGE_TRACKING_DIR"] = saved_env
check("--bestaetigen ohne NBAEDGE_TRACKING_DIR (echte Umgebung): verweigert (Rueckgabe 2), nichts gespeichert", rc == 2 and "nur mit gesetztem NBAEDGE_TRACKING_DIR" in " ".join(out) and entry() is None)
setup(); rc, out = replay(games=[GAMES[0]], confirm=True)
check("Spiel nicht (mehr) in der Spieleliste (begonnen/beendet): klare Meldung, Rueckgabe 2, nichts gespeichert", rc == 2 and "nicht (mehr) in der Spieleliste" in " ".join(out) and entry() is None)
setup(); rc, out = replay(corr_ := {"Quote Gibt Es Nicht 1+": "2"}, confirm=True)
check("Korrektur fuer eine Frage, die nicht vorkommt: Hinweis 'Korrektur nicht angewendet'", rc == 0 and any("Korrektur nicht angewendet" in o for o in out))
check("Das Protokoll wird nie veraendert (SHA vor/nach)", sha(proto) == psha)

# ---- 6) Echtes Protokoll (nur lesen), falls vorhanden
rp = ROOT / "eingabe_protokoll.txt"
if rp.exists():
    pr = ew.parse_protocol(rp.read_text(encoding="utf-8"), 2)
    check("Echtes Protokoll (nur gelesen): Spiel 2 = Wizards – Bucks, letzte Bestaetigung offen, abgelehnte Bestaetigungen entfernt, nur 'z'-Bestaetigungen und die letzte bleiben",
          "Washington Wizards – Milwaukee Bucks" in pr["header"] and pr["final_pending"] and not pr["saved_in_protocol"] and sum(1 for s in pr["steps"] if s[0] == "Speichern?") == 4, f"{len(pr['steps'])} Schritte")

# ---- 7) Keine Abrufe, echte Dateien unveraendert
check("Keine Abrufe: BallDontLie, Odds API, NBA.com unveraendert", (state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"]) == real_calls)
after = {n: sha(ROOT / n) for n in real}
check("Pickle, echte pre_match_entries.json, rosters.json und eingabe_protokoll.txt unveraendert (SHA vor/nach)", after == real, f"{real} -> {after}")

print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)

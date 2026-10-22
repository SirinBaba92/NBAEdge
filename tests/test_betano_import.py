"""Tests fuer betano_import.py (Betano-Quoten aus einem Mitschnitt automatisch in die Pre-Match-Eingabe uebernehmen). Offline, Temp-Ordner; kein Abruf bei Betano.
Testdaten: tests/fixtures/betano_magic_hawks.har.json (nur Antworttexte aus einem eigenen Mitschnitt, ohne Header/Cookies).
Aufruf aus dem Projektordner: venv/bin/python tests/test_betano_import.py"""
import hashlib, json, os, shutil, sys, warnings
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
import betano_import as bi

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha = lambda p: hashlib.sha1(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None
real = {n: sha(ROOT / "data" / n) for n in ("elo_model.pkl", "rosters.json", "tracking/pre_match_entries.json")}
real_calls = state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"]
FIX = ROOT / "tests" / "fixtures" / "betano_magic_hawks.har.json"
REAL_ROSTER = (ROOT / "data" / "rosters.json").read_text()
M, HK = "Orlando Magic", "Atlanta Hawks"
START_MS = 1792623600000
START = "2026-10-21T23:00:00Z"
NOW = START_MS / 1000 - 6 * 3600
G = {"home": M, "away": HK, "date": "2026-10-21", "start": START}
KEY = ps.game_key(G["date"], START, M, HK)


def setup():
    tmp = fresh_env()
    ro.rosters_path().write_text(REAL_ROSTER)
    (tmp / "upcoming_cache.json").write_text(json.dumps({"fetched_at": NOW, "params": {}, "games": [bdl_game()]}))
    return tmp


def bdl_game():
    return {"home_team": {"full_name": M}, "visitor_team": {"full_name": HK}, "date": G["date"], "datetime": START, "status": "scheduled"}


def entry():
    return (ps.load().get("entries") or {}).get(KEY)


def run_import(real_answers, src=FIX, args=None):
    out, asked = [], []
    def real(prompt):
        asked.append(prompt)
        return real_answers.pop(0) if real_answers else "q"
    rc = bi.main(["--datei", str(src)] + (args or []), real=real, write=out.append, now_fn=lambda: NOW)
    return rc, out, asked


# ===== Parser
pay = bi.load_payloads(FIX)
evs = bi.list_events(pay)
check("Mitschnitt gelesen: Spielliste (6) und Detailantwort", len(pay) == 2 and len(evs) == 6 and evs[0]["teams"] == (M, HK))
det = bi.detail_for(pay, evs[0]["id"])
pe = bi.parse_event(det, M, HK)
check("Sieger Heim/Gast: Magic 1.72, Hawks 2.22", pe["winner"] == (1.72, 2.22), str(pe["winner"]))
check("Spread-Hauptlinie aus Heim-Sicht: Magic -2.5; Leiter enthaelt -4.5 (Magic 2.10 / Hawks 1.75)", pe["spread"]["main"] == -2.5 and pe["spread"]["lines"][-4.5] == (2.1, 1.75), str(pe["spread"]["main"]))
check("Total-Hauptlinie 233.5 (Ueber 1.87 / Unter 1.93) und Leiter", pe["total"]["main"] == 233.5 and pe["total"]["lines"][233.5] == (1.87, 1.93) and len(pe["total"]["lines"]) > 10)
check("Team Totals: Magic 118.5 (1.87/1.83)", pe["team"]["home"]["main"] == 118.5 and pe["team"]["home"]["lines"][118.5] == (1.87, 1.83), str(pe["team"]))
check("Spieler-Meilensteine: Banchero 20+ = 1.5 bis 28+ = 3.4", pe["players"]["Paolo Banchero"][20] == 1.5 and pe["players"]["Paolo Banchero"][28] == 3.4 and len(pe["players"]) == 15)

# ===== Komplett-Import mit Speichern
setup()
rc, out, asked = run_import([""])
txt = "\n".join(out)
e = entry()
spl = {l["id"]: l for l in ps.active_spread_lines(e)}
tl = {l["line"]: l for l in ps.active_total_lines(e)}
blocks = {b["name"]: b for b in ps.active_player_blocks(e)}
check("Import + Enter bei 'Speichern?': gespeichert (Antwort kam von der Tastatur), Zusammenfassung angezeigt, genau EINE Tastaturfrage", rc == 0 and "Gespeichert." in txt and len(asked) == 1 and asked[0].startswith("Speichern?") and "Sieger:  Magic 1.72 | Hawks 2.22" in txt)
w = e["markets"]["winner_incl_ot"]
check("Sieger gespeichert (Heim 1.72 / Gast 2.22, Buchmacher Betano)", (w["home_odds"], w["away_odds"], w["bookmaker"]) == (1.72, 2.22, "Betano"))
check("Spread: Hauptlinie -2.5 plus -3.5/-4.5 und -1.5 (die Linie -0.5 gibt es bei Betano nicht), Quoten Heim/Gast korrekt",
      spl["main"]["line_home"] == -2.5 and sorted(l["line_home"] for l in spl.values()) == [-4.5, -3.5, -2.5, -1.5] and next(l for l in spl.values() if l["line_home"] == -4.5)["home_odds"] == 2.1
      and next(l for l in spl.values() if l["line_home"] == -4.5)["away_odds"] == 1.75)
check("Total: Hauptlinie 233.5 plus 3 niedrigere (230.5-232.5) und 3 hoehere (234.5-236.5), Over/Under korrekt",
      sorted(tl) == [230.5, 231.5, 232.5, 233.5, 234.5, 235.5, 236.5] and tl[230.5]["direction"] == "lower" and tl[236.5]["direction"] == "higher" and (tl[233.5]["over_odds"], tl[233.5]["under_odds"]) == (1.87, 1.93)
      and tl[233.5]["id"] == "main")
check("Team Totals: Magic 118.5 (1.87/1.83), Hawks 115.5 (1.82/1.90)", [(l["line"], l["over_odds"], l["under_odds"]) for l in ps.team_total_lines(e, "home")] == [(118.5, 1.87, 1.83)]
      and [(l["line"], l["over_odds"], l["under_odds"]) for l in ps.team_total_lines(e, "away")] == [(115.5, 1.82, 1.9)])
check("Spieler: alle 15 Spieler aus Betano im Kader gefunden, richtiges Team, Meilensteine mit Quoten (Banchero 20+ bis 28+, Dort 5+ bis 10+)",
      len(blocks) == 15 and blocks["Paolo Banchero"]["team"] == M and blocks["Luguentz Dort"]["team"] == HK
      and [(l["threshold"], l["odds"]) for l in ps.player_lines(blocks["Paolo Banchero"])] == [(20 + i, q) for i, q in enumerate([1.5, 1.62, 1.75, 1.93, 2.15, 2.4, 2.7, 3.0, 3.4])]
      and len(ps.player_lines(blocks["Luguentz Dort"])) == 6)

# ===== Zweiter Lauf mit denselben Daten: nichts geaendert
rc, out, asked = run_import([""])
check("Wiederholung mit denselben Betano-Daten: 'Nichts geändert.' (keine neue Revision)", "Nichts geändert." in "\n".join(out))

# ===== n verwirft: nichts gespeichert
setup()
rc, out, asked = run_import(["n"])
check("n bei 'Speichern?': verworfen, nichts gespeichert", entry() is None and "Verworfen." in "\n".join(out))

# ===== Gespeicherte alte Linien: nicht mehr vorhandene werden entfernt (Enter = entfernen), passende ueberschrieben, keine Duplikate
setup()
ou = lambda line, rid=None, d=None: {"id": rid, "direction": d, "line": str(line), "over_odds": "1.9", "under_odds": "1.9", "bookmaker": "Betano"}
ps.save_card(G["date"], START, M, HK, total_rows=[ou(240.5, "main"), ou(233.5, None, "lower"), ou(234.5, None, "higher"), ou(250.5, None, "higher")],
             spread_rows=[{"id": "main", "line": "-7.5", "home_odds": "1.9", "away_odds": "1.9", "bookmaker": "Betano"}, {"id": None, "line": "-2.5", "home_odds": "1.9", "away_odds": "1.9", "bookmaker": "Betano"}], now=NOW)
rc, out, asked = run_import([""])
e = entry(); tl = {l["line"]: l for l in ps.active_total_lines(e)}; sp = sorted(l["line_home"] for l in ps.active_spread_lines(e))
check("Alte Total-Linien (Hauptlinie 240.5, Zusatzlinien 233.5/234.5/250.5): neue Leiter 230.5-236.5, 250.5 entfernt, keine Duplikate, gespeichert",
      "Gespeichert." in "\n".join(out) and sorted(tl) == [230.5, 231.5, 232.5, 233.5, 234.5, 235.5, 236.5] and len(ps.active_total_lines(e)) == 7 and tl[233.5]["id"] == "main", f"{sorted(tl)} {out[-4:]}")
check("Alte Spread-Linien (Hauptlinie -7.5, Zusatzlinie -2.5): neue Hauptlinie -2.5 uebernimmt, Leiter -4.5/-3.5/-1.5 ohne Duplikat", sp == [-4.5, -3.5, -2.5, -1.5], str(sp))

# ===== Spiel nicht in den Betano-Daten / nur Spielplan ohne Quoten
setup()
(ROOT / "tests" / "fixtures").mkdir(exist_ok=True)
rc, out, asked = run_import([""], args=["1"])
check("Spielnummer 1 angegeben: funktioniert wie 'alle'", entry() is not None and rc == 0)
tmp0 = setup()
har = json.loads(FIX.read_text())
har["log"]["entries"] = har["log"]["entries"][1:]                      # nur Spielliste
tmpf = tmp0 / "nur_liste.json"; tmpf.write_text(json.dumps(har))
rc, out, asked = run_import([""], src=tmpf)
check("Quelle mit nur dem Spielplan (keine Quoten des Spiels): Hinweis, nichts gespeichert, kein Absturz", entry() is None and any("keine Quoten" in o for o in out), "\n".join(out)[-300:])
setup()
har = json.loads(FIX.read_text()); d0 = json.loads(har["log"]["entries"][0]["response"]["content"]["text"])
d0["data"]["event"]["participants"] = [{"name": "Boston Celtics", "id": "1"}, {"name": "Miami Heat", "id": "2"}]
har["log"]["entries"] = [{"response": {"content": {"mimeType": "application/json", "text": json.dumps(d0)}}}]
tmpf = fresh_env() / "anderes.json"; tmpf.write_text(json.dumps(har))
setup()
rc, out, asked = run_import([""], src=tmpf)
check("Spiel nicht in der Quelle (andere Mannschaften): uebersprungen, nichts gespeichert", entry() is None and any("nicht in den Betano-Daten" in o for o in out))

# ===== Spieler ausserhalb des Kaders werden uebersprungen und genannt; unbekannte Frage bricht ab
setup()
d1 = json.loads(json.dumps(det)); 
for m in d1["event"]["markets"]:
    if m["type"] == "PLNP":
        m["tableLayout"]["rows"][0]["title"] = "Fantasie Spieler"
har = {"log": {"entries": [{"response": {"content": {"mimeType": "application/json", "text": json.dumps({"data": d1})}}}] + [json.loads(json.dumps(x)) for x in json.loads(FIX.read_text())["log"]["entries"][1:]]}}
tmpf = fresh_env() / "fremd.json"; tmpf.write_text(json.dumps(har)); setup()
rc, out, asked = run_import([""], src=tmpf)
check("Spieler, der nicht im Kader steht: uebersprungen und im Hinweis genannt; die anderen 14 gespeichert", len(ps.active_player_blocks(entry())) == 14 and any("Fantasie Spieler" in o for o in out))
a = bi.AutoAnswers(G, pe, ro.load(), real=lambda p: "", write=lambda x: None)
try:
    a("Voellig neue Frage: ")
    got = None
except bi.ImportAbort as ex:
    got = ex
check("Unbekannte Frage von eingabe.py: Abbruch (ImportAbort) statt zu raten", got is not None)

# ===== Zu viele Spieler (Limit 20): Anzahl wird gekuerzt, kein Endlosschleife
setup()
for_n = ro.load()
ps.save_card(G["date"], START, M, HK, player_blocks=[{"block_id": None, "person_id": p["person_id"], "name": p["name"], "team": HK, "team_abbreviation": "ATL", "mode": "milestones",
                                                      "rows": [{"id": None, "value": "10", "odds": "1.5", "bookmaker": "Betano"}]} for p in for_n["teams"][HK][:12]], now=NOW)
rc, out, asked = run_import([""])
check("12 gespeicherte Spieler des Gast-Teams + 8 Heim-Spieler von Betano: Limit 20 wird eingehalten, kein Endlosschleife, gespeichert", rc == 0 and len(ps.active_player_blocks(entry())) <= 20, f"{len(ps.active_player_blocks(entry()))} {out[-3:]}")

# ===== Team-Total-Leitern (Tab "Alle", bt=6): Hauptlinie bleibt die einzeilige Wette, Zusatzlinien je 3 hoehere und 3 niedrigere
setup()
d2 = json.loads(json.dumps(det))
def ladder(mtype, name, lo, n):
    sels = []
    for i in range(n):
        ln = lo + i
        sels += [{"id": f"{mtype}o{i}", "name": f"Über {ln}", "price": round(1.1 + i * 0.05, 2), "handicap": ln}, {"id": f"{mtype}u{i}", "name": f"Unter {ln}", "price": round(4.5 - i * 0.1, 2), "handicap": ln}]
    return {"id": mtype, "uniqueId": mtype, "name": name, "type": mtype, "handicap": lo, "selections": sels, "scorerSelections": [], "exactScoreSelections": []}
d2["event"]["markets"] += [ladder("OUHO", "Gesamtpunkte Orlando Magic", 106.5, 24), ladder("OUAO", "Gesamtpunkte Atlanta Hawks", 103.5, 24)]
pe2 = bi.parse_event(d2, M, HK)
check("Parser: Team-Total-Leiter (24 Linien, enthaelt die Hauptlinie 118.5) (einzeilige Wette bleibt die Hauptlinie, nicht die 'ausgeglichenste' Leiterlinie)",
      len(pe2["team"]["home"]["lines"]) == 24 and pe2["team"]["home"]["main"] == 118.5 and pe2["team"]["away"]["main"] == 115.5, str(pe2["team"]["home"]["main"]))
tmpf2 = setup() / "alle.json"
tmpf2.write_text(json.dumps({"log": {"entries": [{"response": {"content": {"mimeType": "application/json", "text": json.dumps({"data": d2})}}}] + json.loads(FIX.read_text())["log"]["entries"][1:]}}))
rc, out, asked = run_import([""], src=tmpf2)
e = entry()
home_lines = sorted(l["line"] for l in ps.team_total_lines(e, "home")); away_lines = sorted(l["line"] for l in ps.team_total_lines(e, "away"))
check("Import mit Leitern: Team Total Heim 118.5 plus 3 niedrigere (115.5-117.5) und 3 hoehere (119.5-121.5) (hoechstens 3 je Richtung), Gast 115.5 plus 112.5-114.5 und 116.5-118.5",
      home_lines == [115.5, 116.5, 117.5, 118.5, 119.5, 120.5, 121.5] and away_lines == [112.5, 113.5, 114.5, 115.5, 116.5, 117.5, 118.5] and "Gespeichert." in "\n".join(out), f"{home_lines} {away_lines} {out[-3:]}")

# ===== Abruf (ohne --datei) mit nachgestelltem Abruf: nur Spielliste + Spielseite, mit Pause
setup()
calls = []
orig_fetch, orig_sleep = bi.fetch_json, bi.time.sleep
lst = json.loads(json.loads(FIX.read_text())["log"]["entries"][1]["response"]["content"]["text"])
dtl = json.loads(json.loads(FIX.read_text())["log"]["entries"][0]["response"]["content"]["text"])
bi.fetch_json = lambda path: (calls.append(path), lst if "/api/sport/" in path else dtl)[1]
bi.time.sleep = lambda s_: calls.append(("pause", s_))
try:
    out2 = []
    rc = bi.main([], real=lambda p: "", write=out2.append, now_fn=lambda: NOW)
finally:
    bi.fetch_json, bi.time.sleep = orig_fetch, orig_sleep
check("Ohne Datei (Abruf-Funktion ersetzt, kein Netz): 1 Abruf Spielliste + 1 Abruf Spielseite (/api/quoten/...) mit Pause dazwischen, gespeichert",
      calls[0].startswith("/api/sport/basketball/usa/nba/") and ("pause", bi.PAUSE_SECONDS) in calls and any(isinstance(c, str) and c.startswith("/api/quoten/orlando-magic-atlanta-hawks/91836666/") and c.endswith("&bt=6") for c in calls)
      and len([c for c in calls if isinstance(c, str)]) == 2 and entry() is not None, str(calls))

# ===== Keine Abrufe, echte Dateien unveraendert
check("Keine Abrufe: BallDontLie, Odds API, NBA.com unveraendert", (state["bdl_calls"], len(state["odds_calls"]), state["nba_calls"]) == real_calls)
after = {n: sha(ROOT / "data" / n) for n in real}
check("Pickle, echte pre_match_entries.json und echte rosters.json unveraendert (SHA vor/nach)", after == real, f"{real} -> {after}")
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)

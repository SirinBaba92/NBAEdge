"""Tests fuer Pre-Match Eingabe, Schritt 5: Markt "Total" (Ueber/Unter der Gesamtpunkte) im Speicher und in der Oberflaeche,
ein Speichern fuer drei Maerkte (alles oder nichts), Sperre, Dateiversion 2 -> 3, Knopfstil.
Offline (tests/fake_net.py, Temp-Verzeichnisse), keine echten Calls; Pickle und echte Tracking-Datei nur gelesen.
Aufruf aus dem Projektordner: venv/bin/python tests/test_pre_match_total.py"""
import datetime as dt, hashlib, json, os, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import fake_net
from fake_net import state, fresh_env
fake_net.install(); fresh_env()
import page_checks; page_checks.install()
import data.pre_match_store as ps
import ui.pre_match_tab as pmt
from models.elo import MODEL_PATH
from streamlit.testing.v1 import AppTest

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))

sha0 = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
real_file = ROOT / "data" / "tracking" / "pre_match_entries.json"
real_bytes = real_file.read_bytes() if real_file.exists() else None
H = 3600
iso = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
fsha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
K, P = "New York Knicks", "Philadelphia 76ers"

def trow(rid="main", line="231,5", o="1,91", u="1,89", b="Pinnacle", d=None):
    return {"id": rid, "direction": d, "line": line, "over_odds": o, "under_odds": u, "bookmaker": b}
def srow(rid="main", line="-4,5", h="1,91", a="1,95", b="Pinnacle"):
    return {"id": rid, "line": line, "home_odds": h, "away_odds": a, "bookmaker": b}
def win(h="1,55", a="2,50", b="Betano"): return {"home_odds": h, "away_odds": a, "bookmaker": b}
def card(start, now, winner=None, rows=None, trows=None, tsugg=None, home=K, away=P, date="2026-10-20"):
    return ps.save_card(date, start, home, away, winner=winner, spread_rows=rows, total_rows=trows, total_suggestion=tsugg, now=now)
def fails(fn, exc=ps.OddsInputError):
    try: fn(); return None
    except exc as e: return e

# ===================================================== A) Eingabe: ganze und halbe Linien, 100 bis 400
good = {"231,5": 231.5, "231.5": 231.5, "231": 231.0, " 231,0 ": 231.0, "100": 100.0, "400": 400.0, "99,5": None, "400,5": None}
check("gueltige Total-Linien (Komma/Punkt, ganz/halb, 100 bis 400)", all(ps.parse_total_input(k) == v for k, v in good.items() if v is not None))
bad = ["", " ", None, "abc", "231,25", "231,75", "231,3", "231,1", "1,2,3", "-231,5", "+231,5", "99,5", "99", "400,5", "401", "0", "nan", "inf", "1e3", "231,5x"]
errs = {t: (lambda e: str(e) if e else None)(fails(lambda t=t: ps.parse_total_input(t))) for t in bad}
check("Viertel-/Fremdwerte und Werte ausserhalb 100 bis 400 werden abgelehnt", all(errs.values()), str({k: v for k, v in errs.items() if not v}))
check("Meldungen: Viertellinie, Plausibilitaet", "ganze und halbe" in errs["231,25"] and "unrealistisch" in errs["99,5"] and "unrealistisch" in errs["400,5"] and errs[""] == "Linie fehlt.")

# ===================================================== B) Speichern, Laden, Aendern
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
tsugg = {"line": 231.4, "line_rounded": 231.5, "source": "cache_vorab"}
r = card(start, now, trows=[trow()], tsugg=tsugg)
d = ps.load(); e = list(d["entries"].values())[0]; t = e["markets"]["total"]; l = t["lines"][0]
check("Total gespeichert: Version 5, Hauptlinie main, Linie 231,5, Over/Under, Buchmacher, Zeitstempel, Vorschlag ungerundet + gerundet",
      d["version"] == 5 and r["markets"] == {"winner_incl_ot": "skipped", "spread": "skipped", "total": "saved", "team_totals": "skipped", "player_points": "skipped"} and l["id"] == "main" and l["line"] == 231.5
      and l["over_odds"] == 1.91 and l["under_odds"] == 1.89 and l["bookmaker"] == "Pinnacle" and l["entered_at"] and l["updated_at"] and len(l["revisions"]) == 1
      and l["market_suggestion"] == tsugg and d["last_bookmaker"]["total"] == "Pinnacle" and "total" in d["markets"])
check("Total ohne Vorab-Linie: market_suggestion = null", card(start, now, trows=[trow(line="233", o="1,9", u="1,9")], tsugg=None) and
      ps.load()["entries"] and ps.active_total_lines(list(ps.load()["entries"].values())[0])[0]["market_suggestion"] is None)
b = fsha(ps.store_path()); r = card(start, now + 1, trows=[trow(line="233", o="1,9", u="1,9")])
check("unveraendert speichern: 'unchanged', Datei byte-identisch, keine Revision", r["status"] == "unchanged" and fsha(ps.store_path()) == b)
r = card(start, now + 2, trows=[trow(line="233,5", o="1,9", u="1,9")])
l = ps.active_total_lines(list(ps.load()["entries"].values())[0])[0]
check("Linie geaendert: neue Revision, entered_at bleibt, updated_at neu", r["status"] == "saved" and len(l["revisions"]) == 3 and l["line"] == 233.5 and l["entered_at"] != l["updated_at"])
saved, last = ps.saved_summary(list(ps.load()["entries"].values())[0])
check("Chip: nur Total gespeichert zaehlt als gespeichert", saved and last)

# ===================================================== C) Mehrere Linien: je Richtung bis 3, Duplikate, Entfernen
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
rows = [trow(), trow(None, "232,5", d="higher"), trow(None, "233,5", d="higher"), trow(None, "234,5", d="higher"),
        trow(None, "230,5", d="lower"), trow(None, "229,5", d="lower"), trow(None, "228,5", d="lower")]
r = card(start, now, trows=rows)
e = list(ps.load()["entries"].values())[0]; lines = ps.active_total_lines(e)
check("7 Linien (Hauptlinie + 3 hoehere + 3 niedrigere) gespeichert, Richtungen festgehalten",
      r["status"] == "saved" and [x["id"] for x in lines] == ["main", "x1", "x2", "x3", "x4", "x5", "x6"]
      and [x["direction"] for x in lines] == [None] + ["higher"] * 3 + ["lower"] * 3)
b = fsha(ps.store_path())
x = fails(lambda: card(start, now + 1, trows=[trow(), trow("x1", "232,5", d="higher")] + [trow(None, "240,5", d="higher")]), ps.CardInputError)
check("4. hoehere Linie wird abgelehnt (hoechstens 3), nichts geschrieben", x and "höchstens 3 höhere" in str(x) and fsha(ps.store_path()) == b)
extra = [trow(x_id, ln, d=dd) for x_id, ln, dd in (("x1", "232,5", "higher"), ("x2", "233,5", "higher"), ("x3", "234,5", "higher"), ("x4", "230,5", "lower"), ("x5", "229,5", "lower"), ("x6", "228,5", "lower"))]
x = fails(lambda: card(start, now + 1, trows=[trow()] + extra + [trow(None, "227,5", d="lower")]), ps.CardInputError)
check("4. niedrigere Linie wird abgelehnt (hoechstens 3)", x and "höchstens 3 niedrigere" in str(x) and fsha(ps.store_path()) == b)
x = fails(lambda: card(start, now + 1, trows=[trow()] + [dict(z, line="231,5") if z["id"] == "x2" else z for z in extra]), ps.CardInputError)
check("gespeicherte Linie so geaendert, dass sie die Hauptlinie doppelt: Warnung, nichts geschrieben", x and "mehrfach" in str(x) and "231,5" in str(x) and fsha(ps.store_path()) == b, str(x))
x = fails(lambda: card(start, now + 1, trows=[trow()] + extra + [trow(None, "233,5", d="higher")]), ps.CardInputError)
check("neue Zeile doppelt eine gespeicherte Linie: Warnung, nichts geschrieben", x and "mehrfach" in str(x) and fsha(ps.store_path()) == b)
x = fails(lambda: card(start, now + 1, trows=[trow(line="232,5")] + extra), ps.CardInputError)
check("Hauptlinie nachtraeglich auf eine vorhandene Linie gesetzt: Warnung", x and "mehrfach" in str(x))
r = card(start, now + 2, trows=[trow(line="240")] + extra)
e = list(ps.load()["entries"].values())[0]; lines = ps.active_total_lines(e)
check("Hauptlinie nachtraeglich geaendert verschiebt die weiteren Linien nicht", r["status"] == "saved" and lines[0]["line"] == 240.0 and [x["line"] for x in lines[1:]] == [232.5, 233.5, 234.5, 230.5, 229.5, 228.5])
r = ps.remove_total_line("2026-10-20", start, K, P, "x2", now=now + 3)
e = list(ps.load()["entries"].values())[0]; allx = e["markets"]["total"]["lines"]; rem = next(x for x in allx if x["id"] == "x2")
check("Entfernen: Linie inaktiv, removed_at, Revision 'removed', nichts geloescht", r["status"] == "removed" and rem["active"] is False and rem["removed_at"] and rem["revisions"][-1]["action"] == "removed" and len(allx) == 7 and len(ps.active_total_lines(e)) == 6)
check("Hauptlinie kann nicht entfernt werden", fails(lambda: ps.remove_total_line("2026-10-20", start, K, P, "main", now=now + 4)))
r = card(start, now + 5, trows=[trow(line="240")] + [z for z in extra if z["id"] != "x2"] + [trow(None, "233,5", d="higher")])
check("entfernte Linie darf neu angelegt werden (gleicher Wert wie die inaktive)", r["status"] == "saved" and len(ps.active_total_lines(list(ps.load()["entries"].values())[0])) == 7)

# ===================================================== D) Ein Knopf, drei Maerkte (alles oder nichts)
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
r = card(start, now, winner=win(), rows=[srow()], trows=[trow()])
e = list(ps.load()["entries"].values())[0]
check("alle drei Maerkte in EINEM Schreibvorgang (gleicher Zeitstempel)", r["markets"] == {"winner_incl_ot": "saved", "spread": "saved", "total": "saved", "team_totals": "skipped", "player_points": "skipped"}
      and e["markets"]["winner_incl_ot"]["updated_at"] == e["markets"]["spread"]["updated_at"] == e["markets"]["total"]["updated_at"])
b = fsha(ps.store_path())
r = card(start, now + 1, winner=win(), rows=[srow()], trows=[trow()])
check("alles unveraendert: 'unchanged', byte-identisch, keine Revision", r["status"] == "unchanged" and set(r["markets"].values()) == {"unchanged", "skipped"} and fsha(ps.store_path()) == b)
r = card(start, now + 2, winner=win(), rows=[srow()], trows=[trow(o="1,95")])
e = list(ps.load()["entries"].values())[0]
check("nur Total geaendert: Sieger und Spread ohne neue Revision", r["markets"] == {"winner_incl_ot": "unchanged", "spread": "unchanged", "total": "saved", "team_totals": "skipped", "player_points": "skipped"} and len(e["markets"]["winner_incl_ot"]["revisions"]) == 1 and len(e["markets"]["spread"]["lines"][0]["revisions"]) == 1 and len(e["markets"]["total"]["lines"][0]["revisions"]) == 2)
b = fsha(ps.store_path())
blocks = {
    "Sieger ungueltig blockiert Spread und Total": dict(winner=win(h="abc"), rows=[srow(h="1,92")], trows=[trow(o="2,00")], needle="Sieger inkl. OT"),
    "Spread ungueltig (Viertellinie) blockiert Sieger und Total": dict(winner=win(h="1,60"), rows=[srow(line="-4,25")], trows=[trow(o="2,00")], needle="Spread"),
    "Total ungueltig (Viertellinie) blockiert Sieger und Spread": dict(winner=win(h="1,60"), rows=[srow(h="1,92")], trows=[trow(line="231,25")], needle="Total"),
    "Total ausserhalb 100 bis 400 blockiert alles": dict(winner=win(h="1,60"), rows=[srow(h="1,92")], trows=[trow(line="99")], needle="Total"),
    "Total mit nur einer Quote blockiert alles": dict(winner=win(h="1,60"), rows=[srow(h="1,92")], trows=[trow(u="")], needle="Total"),
}
for name, kw in blocks.items():
    needle = kw.pop("needle")
    x = fails(lambda: card(start, now + 3, **kw), ps.CardInputError)
    check(name + " (Warnung nennt den Markt, Datei unveraendert)", x and any(needle in m for m in x.errors) and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
x = fails(lambda: card(start, now + 3, winner=win(h="x"), rows=[srow(line="-4,3")], trows=[trow(line="231,3")]), ps.CardInputError)
check("mehrere Maerkte falsch: eine Warnung je Markt", x and len(x.errors) == 3 and fsha(ps.store_path()) == b, str(getattr(x, "errors", x)))
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
r = card(start, now, trows=[trow(o="", u="")], winner=win("", ""), rows=[srow(h="", a="")]) if False else None
x = fails(lambda: card(start, now, trows=[trow(o="", u="")]), ps.OddsInputError)
check("vorbefuellte Total-Linie ohne Quoten gilt nicht als ausgefuellt ('Nichts eingetragen'), nichts geschrieben", x and "Nichts eingetragen" in str(x) and not ps.store_path().exists())
x = fails(lambda: card(start, now, trows=[trow(None, "232,5", d="higher")]), ps.OddsInputError)
check("weitere Linie ohne Hauptlinie wird abgelehnt", x and "Hauptlinie" in str(x) and not ps.store_path().exists())

# ===================================================== E) Sperre ab Anpfiff (Speicher, inkl. Rennen)
tmp = fresh_env(); now = time.time(); start_ts = now + 600; start = iso(start_ts)
card(start, now, trows=[trow()]); b = fsha(ps.store_path())
for name, ts in (("genau zum Anpfiff", start_ts), ("nach dem Anpfiff", start_ts + 5)):
    x = fails(lambda ts=ts: card(start, ts, winner=win(), rows=[srow()], trows=[trow(o="2,00")]), ps.GameStartedError)
    check(f"Total-Speichern {name}: abgelehnt, Datei unveraendert", x and fsha(ps.store_path()) == b)
x = fails(lambda: ps.remove_total_line("2026-10-20", start, K, P, "x1", now=start_ts + 1), ps.GameStartedError)
check("Total-Linie entfernen nach Anpfiff: abgelehnt", x)
r = card(start, start_ts - 1, trows=[trow(o="2,00")])
check("eine Sekunde vor dem Anpfiff: noch moeglich", r["status"] == "saved")

# ===================================================== F) Dateiversion 2 bleibt lesbar, wird beim Schreiben byte-genau gesichert
tmp = fresh_env(); now = time.time(); start = iso(now + 3 * H)
v2 = {"version": 2, "format": "nbaedge-pre-match-entries", "markets": {"winner_incl_ot": "x", "spread": "y"}, "last_bookmaker": {"winner_incl_ot": "Betano"}, "updated_at": "2026-10-21T01:10:31+02:00",
      "entries": {f"2026-10-20|{start}|{K}|{P}": {"game_date": "2026-10-20", "start_utc": start, "home": K, "away": P, "markets": {
          "winner_incl_ot": {"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "entered_at": "2026-10-21T01:10:31+02:00", "updated_at": "2026-10-21T01:10:31+02:00",
                             "revisions": [{"home_odds": 1.5, "away_odds": 2.6, "bookmaker": "Betano", "saved_at": "2026-10-21T01:10:31+02:00"}]}}}}}
ps.store_path().parent.mkdir(parents=True, exist_ok=True); ps.store_path().write_text(json.dumps(v2, indent=2)); old = ps.store_path().read_bytes()
d = ps.load()
check("Version-2-Datei ist lesbar, Lesen aendert nichts", not d.get("error") and d["version"] == 2 and ps.store_path().read_bytes() == old and ps.active_total_lines(list(d["entries"].values())[0]) == [])
r = card(start, now, winner=win("1,50", "2,60"), trows=[trow()])
backups = list(ps.history_dir().glob("pre_match_entries.v2_vor_Upgrade_*.json")); d = ps.load(); w = list(d["entries"].values())[0]["markets"]["winner_incl_ot"]
check("erstes Schreiben: Version-2-Datei byte-genau gesichert, Datei Version 5, Sieger unveraendert (keine Revision)", len(backups) == 1 and backups[0].read_bytes() == old and d["version"] == 5
      and w == v2["entries"][f"2026-10-20|{start}|{K}|{P}"]["markets"]["winner_incl_ot"] and r["markets"]["winner_incl_ot"] == "unchanged" and r["markets"]["total"] == "saved")

# ===================================================== G) Oberflaeche (AppTest): Vorschlag, Reihenfolge, Knoepfe, Warnungen
fresh_env(remaining=400)
n = time.time()
def mk_event(home, away, total, home_points, commence, eid):
    bms = []
    for bk, hp in zip(("pinnacle", "draftkings", "fanduel")[:len(home_points)], home_points):
        ms = [{"key": "totals", "last_update": iso(n - 700), "outcomes": [{"name": "Over", "point": total, "price": 1.9}, {"name": "Under", "point": total, "price": 1.9}]},
              {"key": "spreads", "last_update": iso(n - 700), "outcomes": [{"name": home, "point": hp, "price": 1.9}, {"name": away, "point": -hp, "price": 1.9}]}]
        bms.append({"key": bk, "last_update": iso(n - 700), "markets": ms})
    return {"id": eid, "home_team": home, "away_team": away, "commence_time": iso(commence), "bookmakers": bms}
state["commence_offsets"] = {K: 3 * H, "San Antonio Spurs": 3 * H, "Detroit Pistons": -600}
Path(os.environ["NBAEDGE_ODDS_CACHE"]).write_text(json.dumps({"entries": {"totals_spreads": {"fetched_at": n - 600, "markets": "totals,spreads", "regions": "us,eu",
    "data": [mk_event(K, P, 231.4 if False else 232.0, [-4.5, -4.5, -4.0], n + 3 * H, "ev-k")]}}, "credits": {"remaining": 400, "updated_at": n}, "last_error": {}}))
def app(): return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
def btn(at, key): return [b for b in at.button if b.key == key][0]
def ti(at, key): return at.text_input(key=key)
def kid_of(at, home):
    p = [x for x in at.session_state["projections"] if x["home_team"] == home][0]
    return hashlib.md5(ps.game_key(p["game_date"], ps.normalize_start(p["game_start"]), p["home_team"], p["away_team"]).encode()).hexdigest()[:10]
def tkeys(at, kid): return [t.key for t in at.text_input if (t.key or "").startswith(f"pm_tt_{kid}_") and t.key.endswith("_line")]
def clean(at): return not page_checks.problems(at)

at = app().run(); kid = kid_of(at, K); mb = f"pm_tt_{kid}_main"
check("Start: keine Exception/Warnung", clean(at), str(page_checks.problems(at)))
check("Total-Hauptlinie mit der Vorab-Marktlinie vorbefuellt (232,0)", ti(at, f"{mb}_line").value == "232,0", ti(at, f"{mb}_line").value)
cap = [c.value for c in at.caption if "Vorschlag aus Markt (Vorab-Linie): 232,0" in c.value]
check("Vorschlag-Zeile 'Vorschlag aus Markt (Vorab-Linie): 232,0' (ohne 'gerundet', da schon halb)", len(cap) == 1 and "gerundet" not in cap[0], str(cap))
def labels(at): return [m.value for m in at.markdown if "pm-flabel" in m.value]
check("Beschriftungen 'Quote Over · 232,0' / 'Quote Under · 232,0' (ueber dem Feld, Widget-Label bleibt fest)", sum("Quote Over · 232,0<" in v for v in labels(at)) >= 1 and sum("Quote Under · 232,0<" in v for v in labels(at)) >= 1)
others = [x for x in at.session_state["projections"] if x["home_team"] != K and x["game_start"] and ps.is_editable(ps.normalize_start(x["game_start"]))]
sp = [x for x in at.session_state["projections"] if x["home_team"] == "San Antonio Spurs"][0]; kid_s = kid_of(at, "San Antonio Spurs")
check("Ohne Vorab-Linie bleibt das Total-Feld leer und es gibt keine Vorschlagzeile", ti(at, f"pm_tt_{kid_s}_main_line").value == "" and not [c for c in at.caption if "Vorschlag" in c.value and False])
check("Reihenfolge der Total-Felder: Linie, Quote Over, Buchmacher, Quote Under", [t.key for t in at.text_input if (t.key or "").startswith(mb)] == [f"{mb}_line", f"{mb}_over", f"{mb}_book", f"{mb}_under"])

# Klicks
ti(at, f"{mb}_over").input("1,95").run()
btn(at, f"{mb}_plus").click().run()
check("+ erhoeht die Linie um 0,5; Beschriftung folgt; eingegebene Quote bleibt erhalten", ti(at, f"{mb}_line").value == "232,5" and any("Quote Over · 232,5<" in v for v in labels(at)) and ti(at, f"{mb}_over").value == "1,95", ti(at, f"{mb}_over").value)
btn(at, f"{mb}_minus").click().run(); btn(at, f"{mb}_minus").click().run()
check("- senkt um 0,5 pro Klick", ti(at, f"{mb}_line").value == "231,5")
ti(at, f"{mb}_line").input("231.5").run()
check("Eingabe mit Punkt wird akzeptiert", clean(at) and ti(at, f"{mb}_line").value == "231.5")
btn(at, f"{mb}_plus").click().run()
check("+ nach Punkt-Eingabe: 232,0", ti(at, f"{mb}_line").value == "232,0")
hi, lo = f"pm_tt_{kid}__addh", f"pm_tt_{kid}__addl"
check("Knoepfe '+ Hoehere Linie' und '- Niedrigere Linie' sind sekundaer (grau, nie primary)", all(btn(at, k).proto.type != "primary" for k in (hi, lo)) and btn(at, hi).label in ("+ Höhere Linie", "\\+ Höhere Linie") and btn(at, lo).label == "− Niedrigere Linie", btn(at, hi).label)
for i in range(3): btn(at, hi).click().run()
vals = [ti(at, k).value for k in tkeys(at, kid) if not k.endswith("_main_line")]
check("hoehere Linien automatisch 1,0 weiter: 233,0 / 234,0 / 235,0", sorted(vals) == ["233,0", "234,0", "235,0"], str(vals))
check("nach 3 hoeheren: Knopf deaktiviert, Notiz 'maximal 3 höhere Linien'", btn(at, hi).disabled and any(c.value == "maximal 3 höhere Linien" for c in at.caption) and not btn(at, lo).disabled)
for i in range(3): btn(at, lo).click().run()
vals = [ti(at, k).value for k in tkeys(at, kid) if not k.endswith("_main_line")]
check("niedrigere Linien: 231,0 / 230,0 / 229,0; Maximum 3 mit Notiz 'maximal 3 niedrigere Linien'", sorted(vals) == ["229,0", "230,0", "231,0", "233,0", "234,0", "235,0"] and btn(at, lo).disabled and any(c.value == "maximal 3 niedrigere Linien" for c in at.caption))
order = [ti(at, k).value for k in tkeys(at, kid)]
check("Darstellung nach Linie sortiert: Hauptlinie oben, im Expander hoehere (235 > 234 > 233) dann niedrigere (231 > 230 > 229)", order == ["232,0", "235,0", "234,0", "233,0", "231,0", "230,0", "229,0"], str(order))
check("Expander-Titel 'Weitere Linien (0)' vor dem Speichern, alle Klicks ohne Warnung/Exception", clean(at), str(page_checks.problems(at)))
rm_keys = [k for k in (b.key or "" for b in at.button) if k.startswith(f"pm_tt_{kid}_n") and k.endswith("_rm")]
check("6 'Entfernen'-Knoepfe (tertiaer, dezent), kein Entfernen bei der Hauptlinie", len(rm_keys) == 6 and all(btn(at, k).proto.type == "tertiary" for k in rm_keys) and f"{mb}_rm" not in [b.key for b in at.button])
nids = [k.split("_")[3] for k in rm_keys]
btn(at, f"pm_tt_{kid}_{nids[0]}_rm").click().run()
check("Entfernen einer neuen Zeile verwirft sie (5 weitere uebrig), Hinzufuegen wieder moeglich", len(tkeys(at, kid)) == 6 and clean(at))
check("Speichern ist der einzige primaere (orange) Knopf der Karte", [b.key for b in at.button if b.proto.type == "primary" and kid in (b.key or "")] == [f"pm_save_{kid}"] and btn(at, f"pm_save_{kid}").proto.type == "primary",
      str([(b.key, b.proto.type) for b in at.button if kid in (b.key or "") and b.proto.type == "primary"]))

# Speichern: drei Maerkte in einem Klick; Winner ungueltig blockiert alles
real_before_ui = real_file.read_bytes() if real_file.exists() else None
def fill_row(a, k, o, u, bk="Pinnacle"):
    ti(a, f"pm_tt_{kid}_{k}_over").input(o); ti(a, f"pm_tt_{kid}_{k}_under").input(u); ti(a, f"pm_tt_{kid}_{k}_book").input(bk)
ti(at, f"pm_home_{kid}").input("abc"); ti(at, f"pm_away_{kid}").input("2,5")
ti(at, f"pm_sp_{kid}_main_away").input("1,95"); ti(at, f"pm_sp_{kid}_main_home").input("1,91")
fill_row(at, "main", "1,95", "1,87")
for k in tkeys(at, kid):
    if not k.endswith("_main_line"): fill_row(at, k.split("_")[3], "1,90", "1,90")
btn(at, f"pm_save_{kid}").click().run()
w = [x.value for x in at.warning]
check("Speichern mit falschem Sieger: Warnung 'Sieger inkl. OT', es wird nichts gespeichert (auch Total und Spread nicht)", any("Sieger inkl. OT" in x for x in w) and not ps.store_path().exists(), str(w))
ti(at, f"pm_home_{kid}").input("1,60"); btn(at, f"pm_save_{kid}").click().run()
e = list(ps.load()["entries"].values())[0]
check("Speichern mit korrekten Werten: Sieger, Spread und Total (Hauptlinie + 5 weitere) in einem Schreibvorgang",
      set(e["markets"]) == {"winner_incl_ot", "spread", "total"} and len(ps.active_total_lines(e)) == 6 and e["markets"]["total"]["lines"][0]["market_suggestion"] == {"line": 232.0, "line_rounded": 232.0, "source": "cache_vorab"}, str(set(e["markets"])))
at = app().run(); kid = kid_of(at, K); mb = f"pm_tt_{kid}_main"
check("Neu laden: gespeicherte Total-Linien sortiert und gefuellt, keine Warnung", clean(at) and ti(at, f"{mb}_over").value == "1,95" and any("Quote Over · 232,0<" in v for v in labels(at)), str(page_checks.problems(at)))
xs = [k for k in tkeys(at, kid) if not k.endswith("_main_line")]
order = [ti(at, k).value for k in tkeys(at, kid)]
check("gespeicherte Linien: hoehere oben, niedrigere darunter", order[0] == "232,0" and order[1:] == sorted(order[1:3], reverse=True) + sorted(order[3:], reverse=True) and len(order) == 6, str(order))
# doppelte Linie ueber +/-: erste weitere Linie auf die Hauptlinie setzen
first_hi = xs[0].rsplit("_line", 1)[0]
ti(at, f"{first_hi}_line").input("232,0").run()
btn(at, f"pm_save_{kid}").click().run()
check("Linie per Eingabe auf die Hauptlinie gesetzt: gelbe Warnung 'mehrfach', nichts gespeichert", any("mehrfach" in x.value for x in at.warning) and len(ps.active_total_lines(list(ps.load()["entries"].values())[0])) == 6, str([x.value for x in at.warning]))
# Entfernen einer gespeicherten Linie
at = app().run(); kid = kid_of(at, K)
rid = [k for k in tkeys(at, kid) if not k.endswith("_main_line")][0].split("_")[3]
btn(at, f"pm_tt_{kid}_{rid}_rm").click().run()
e = list(ps.load()["entries"].values())[0]
check("Entfernen einer gespeicherten Total-Linie: inaktiv + Revision, 5 aktive uebrig", len(ps.active_total_lines(e)) == 5 and sum(1 for x in e["markets"]["total"]["lines"] if not x["active"]) == 1)
# Rennen: Seite wurde vor dem Anpfiff gerendert, Klick nach dem Anpfiff
at = app().run(); kid = kid_of(at, K)
b = fsha(ps.store_path()); ti(at, f"pm_tt_{kid}_main_over").input("2,22")
real_now = pmt._now; calls = {"n": 0}
def late_now():                                   # erster Aufruf (Seite zeichnen): jetzt; spaeter (Speichern): nach dem Anpfiff
    calls["n"] += 1
    return time.time() if calls["n"] == 1 else time.time() + 4 * H
pmt._now = late_now
btn(at, f"pm_save_{kid}").click().run(); pmt._now = real_now
check("Rennen (Seite offen, Anpfiff vorbei): Speichern wird abgelehnt, Datei unveraendert", any("begonnen" in x.value for x in at.warning) and fsha(ps.store_path()) == b, str([x.value for x in at.warning]))
# gesperrtes Spiel (Detroit, begonnen) zeigt nur gespeicherte Werte
at = app().run()
lk = [x for x in at.markdown if "Keine Total-Linie vor dem Anpfiff eingetragen." in x.value]
check("laufendes Spiel: nur Anzeige ('Keine Total-Linie vor dem Anpfiff eingetragen.'), keine Total-Felder", lk and not [t for t in at.text_input if (t.key or "").startswith("pm_tt_") and t.key.split("_")[2] not in (kid, kid_s)])
check("Knopfstil im CSS: Orange nur fuer primary, tertiary transparent, Rest grau", 'stBaseButton-primary"] {' in pmt.PRE_MATCH_CSS and "stBaseButton-tertiary" in pmt.PRE_MATCH_CSS and "background:#222842" in pmt.PRE_MATCH_CSS)
check("echtes Pickle unveraendert", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == sha0)
check("echte Tracking-Datei byte-identisch", (real_file.read_bytes() if real_file.exists() else None) == real_bytes)
check("in KEINEM AppTest-Lauf Exception oder 'default value'-Satz", not page_checks.bad, str(page_checks.bad[:3]))
print("\nErgebnis:", "ALLE TESTS BESTANDEN" if ok else "FEHLER")
sys.exit(0 if ok else 1)

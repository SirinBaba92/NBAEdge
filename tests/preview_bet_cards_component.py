"""Vorschau und Selbsttest der Karten-Komponente (ui/components/bet_cards/index.html) ohne App und ohne Netz.
  venv/bin/python tests/preview_bet_cards_component.py [Ausgabedatei]      schreibt eine HTML-Datei mit Beispieldaten (Standard: /tmp/nbaedge_wettschein_vorschau.html), im Browser oeffnen:
      Zeilen anklicken, zweiter Klick beim selben Spieler ersetzt, Einsatz aendern, Leeren, 'Alle speichern' (Antwort der App wird simuliert: Carla scheitert absichtlich), Spiel wechseln.
  venv/bin/python tests/preview_bet_cards_component.py --autotest          startet Chrome unsichtbar, spielt ein Skript durch (Klicken, Ersetzen, Summen, Neu-Rendern, Speichern, Teilfehler,
      doppelte Antwort, Spielwechsel) und gibt PASS/FAIL aus (braucht Google Chrome unter /Applications).
Die echte App und die Wettliste werden nicht beruehrt."""
import os, subprocess, sys, tempfile, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from ui import player_view as pv

def player(pid, name, abbr, pts, quotes, model, warn=None):
    return {"person_id": pid, "name": name, "team": "Heim Falken", "team_abbreviation": abbr, "ok": True, "reason": None, "quality": [], "warnings": [warn] if warn else [],
            "minutes": {"base": 30.0, "mean": 30.0, "role": "Stamm"}, "minutes_adjusted": 30.0, "expected_points_raw": pts, "expected_points_adjusted": pts,
            "p_ge_raw": {str(k): v for k, v in model.items()}, "p_ge_adjusted": {str(k): v for k, v in model.items()},
            "quotes": [{"milestone": n, "odds": o, "bookmaker": "Betano", "bookmaker_probability": bp, "bookmaker_percent": round(bp * 100)} for n, o, bp in quotes]}
ENTRY = {"game_key": "k", "players": [
    player(1, "Anna Alpha", "HEI", 22.0, [(15, 1.30, .75), (20, 1.85, .54), (25, 3.0, .32)], {15: .90, 20: .64, 25: .30}, warn="Rollenwechsel"),
    player(2, "Berta Beta", "HEI", 14.0, [(10, 1.50, .64), (15, 2.20, .44)], {10: .52, 15: .40}),
    player(3, "Carla Gamma", "GAS", 18.0, [(15, 1.60, .60), (20, 2.00, .49), (25, 3.50, .27)], {15: .62, 20: .45, 25: .20}),
    player(4, "Dora Delta", "GAS", 12.0, [(10, 1.40, .70), (15, 2.40, .40)], {10: .75, 15: .42})]}
CARDS = pv.render_cards_html(pv.build_table_model(ENTRY, "team", "team"))
CARDS2 = pv.render_cards_html(pv.build_table_model(ENTRY, "raw", "minutes"))          # anderer Modus: andere Reihenfolge, Auswahl muss bleiben
CSS = pv.PLAYER_CSS + pv.CARDS_CSS
ARGS = {"html": CARDS, "css": CSS, "game_key": "2099-01-01|2099-01-02T01:00:00Z|Heim Falken|Gast Baeren", "locked": {"4": 10}, "default_stake": 10.0, "result": None}

DRIVER = r"""
<script>
(function () {
  var A = %(args)s, A2 = %(args2)s, AUTOTEST = %(auto)s, out = [], sent = [], heights = [], serverBets = {};
  function render(extra) { var a = JSON.parse(JSON.stringify(A)); for (var k in extra) a[k] = extra[k]; window.postMessage({ isStreamlitMessage: true, type: "streamlit:render", args: a }, "*"); }
  // simulierte App: antwortet auf 'save' nach 300 ms; Carla (3) scheitert absichtlich
  window.addEventListener("message", function (ev) {
    var d = ev.data; if (d && d.type === "streamlit:setFrameHeight") heights.push(d.height);
    if (!d || d.type !== "streamlit:setComponentValue") return;
    var v = d.value; sent.push(v);
    setTimeout(function () {
      var saved = [], failed = [];
      v.items.forEach(function (x) { if (x.player === 3) failed.push({ player: 3, name: x.name, milestone: x.milestone, reason: "Testfehler: Wette absichtlich abgelehnt" }); else { saved.push(x.player); serverBets[x.player] = x.milestone; } });
      lockedNow = JSON.parse(JSON.stringify(A.locked)); for (var p in serverBets) lockedNow[p] = serverBets[p];
      A.locked = lockedNow; A.result = { nonce: v.nonce, saved: saved, failed: failed };
      render({});
    }, 300);
  });
  var lockedNow = A.locked;
  window.addEventListener("load", function () { setTimeout(function () { render({}); if (AUTOTEST) setTimeout(run, 200); }, 50); });

  // ---------- Selbsttest
  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function row(pid, n) { return $('#cards .pl-c-row[data-pid="' + pid + '"][data-n="' + n + '"]'); }
  function click(el) { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
  function check(name, cond, info) { out.push((cond ? "PASS " : "FAIL ") + name + (cond ? "" : "  [" + info + "]")); }
  function txt(s) { var e = $(s); return e ? e.textContent : ""; }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function contentH() { return Math.ceil(document.getElementById("root").getBoundingClientRect().height) + 2; }
  function lastHeight() { return heights[heights.length - 1]; }
  async function run() {
    try {
      await wait(100);
      var h0 = lastHeight();
      check("Schein steht OBEN, vor den Karten (normaler Block, nicht fixiert)", !!($("#bar").compareDocumentPosition($("#cards")) & Node.DOCUMENT_POSITION_FOLLOWING) && getComputedStyle($("#bar")).position === "static", getComputedStyle($("#bar")).position);
      check("leerer Schein: nur schmale Zeile 'Wettschein: nichts ausgewählt. Meilenstein-Zeilen anklicken.'", /Wettschein: nichts ausgewählt\. Meilenstein-Zeilen anklicken\./.test(txt("#bar")) && $("#bar").getBoundingClientRect().height < 60 && $$(".bc-item").length === 0, $("#bar").getBoundingClientRect().height);
      var scrolls = $$("*").filter(function (e) { var o = getComputedStyle(e); return /(auto|scroll)/.test(o.overflowY) && e.scrollHeight > e.clientHeight; });
      check("keine innere Scrollleiste: Kartenflaeche overflow visible, kein scrollbarer Bereich im Rahmen", getComputedStyle($("#cards")).overflowY === "visible" && scrolls.length === 0 && getComputedStyle(document.documentElement).overflowY !== "scroll", scrolls.length);
      check("gemeldete Rahmenhoehe = Inhaltshoehe (Karten in voller Laenge, nicht fest)", typeof h0 === "number" && Math.abs(h0 - contentH()) <= 2 && h0 >= $("#cards").scrollHeight + $("#bar").offsetHeight, h0 + " vs " + contentH());
      check("Karten gerendert, Zeilen tragen Haeckchenfeld", $$("#cards .pl-c-row[data-pid]").length === 10 && $$("#cards .bc-cb").length === 10, $$("#cards .pl-c-row[data-pid]").length);
      check("bereits gesetzte Wette: '✓ gesetzt' und nicht anklickbar; andere Meilensteine des Spielers gesperrt", row(4, 10).classList.contains("bc-set") && /gesetzt/.test(row(4, 10).textContent) && row(4, 15).classList.contains("bc-locked"));
      click(row(4, 15)); click(row(4, 10));
      check("Klick auf gesperrte/gesetzte Zeile aendert nichts", $$(".bc-sel").length === 0 && /Meilenstein-Zeilen anklicken/.test(txt("#bar")));
      click(row(1, 20));
      check("Klick waehlt: Zeile orange (bc-sel) mit Haken, Schein zeigt '1 Wette'", row(1, 20).classList.contains("bc-sel") && /✓/.test(row(1, 20).querySelector(".bc-cb").textContent) && /1 Wette/.test(txt(".bc-count")));
      await wait(100);
      check("Schein klappt auf, Rahmenhoehe waechst mit und entspricht dem Inhalt", lastHeight() > h0 && Math.abs(lastHeight() - contentH()) <= 2 && $("#bar").getBoundingClientRect().height > 100, h0 + " -> " + lastHeight() + " vs " + contentH());
      click(row(1, 15));
      check("zweiter Klick beim selben Spieler ersetzt, Hinweis 'Bei Anna Alpha ersetzt: 20+ → 15+'", !row(1, 20).classList.contains("bc-sel") && row(1, 15).classList.contains("bc-sel") && /Bei Anna Alpha ersetzt: 20\+ → 15\+/.test(txt("#bc-msg")) && $$(".bc-item").length === 1, txt("#bc-msg"));
      click(row(2, 10)); click(row(3, 25));
      check("3 Wetten, Gesamteinsatz 30,00 € (Standard 10), Ø Quote (1,30+1,50+3,50)/3 = 2,10", $$(".bc-item").length === 3 && txt("#bc-sum") === "30,00 €" && txt("#bc-avg") === "2,10", txt("#bc-sum") + " " + txt("#bc-avg"));
      click(row(1, 15));
      check("nochmal klicken nimmt die Wahl zurueck", !row(1, 15).classList.contains("bc-sel") && $$(".bc-item").length === 2 && /2 Wetten/.test(txt(".bc-count")));
      click(row(1, 20));
      var inp = $('input[data-stake="2"]'); inp.value = "12,5"; inp.dispatchEvent(new Event("input", { bubbles: true }));
      check("Einsatz aendern (Komma): Gesamteinsatz 32,50 €", txt("#bc-sum") === "32,50 €", txt("#bc-sum"));
      render({}); await wait(50);
      check("Neu-Rendern mit gleichen Argumenten (30-s-Takt): Auswahl und Einsaetze bleiben", $$(".bc-item").length === 3 && $('input[data-stake="2"]').value === "12,5" && row(2, 10).classList.contains("bc-sel"));
      render({ html: A2.html }); await wait(50);
      check("Moduswechsel (andere Karten-Reihenfolge): Auswahl bleibt, Zeilen markiert", $$(".bc-item").length === 3 && row(3, 25).classList.contains("bc-sel") && row(1, 20).classList.contains("bc-sel"));
      render({ html: A2.html.replace(/<div class='pl-c-row[^>]*data-pid='3'[^>]*data-n='25'[\s\S]*?<\/div><\/div><\/div>/, "") }); await wait(50);
      check("Meilenstein nicht mehr sichtbar: bleibt im Schein", $$(".bc-item").length === 3);
      render({ html: A2.html, game_key: "ANDERES|SPIEL" }); await wait(50);
      check("anderes Spiel: eigener, leerer Schein (Auswahl des ersten Spiels nicht mit dabei)", $$(".bc-item").length === 0 && /nichts ausgewählt/.test(txt("#bar")));
      render({ html: A2.html }); await wait(50);
      check("zurueck zum ersten Spiel: Auswahl noch da", $$(".bc-item").length === 3);
      inp = $('input[data-stake="2"]'); inp.value = "abc"; inp.dispatchEvent(new Event("input", { bubbles: true }));
      click($("#bc-save")); await wait(50);
      check("ungueltiger Einsatz: rote Meldung, nichts gesendet", sent.length === 0 && /Einsatz muss eine Zahl/.test(txt("#bc-msg")), txt("#bc-msg"));
      inp = $('input[data-stake="2"]'); inp.value = "12,5"; inp.dispatchEvent(new Event("input", { bubbles: true }));
      click($("#bc-save")); await wait(60);
      var v = sent[0];
      check("'Alle speichern' sendet Aktion mit nonce und 3 Zeilen (Spieler, Meilenstein, Quote, Einsatz)", sent.length === 1 && v.action === "save" && v.nonce.length > 8 && v.items.length === 3 && v.items[0].quote > 1 && v.items.some(function (x) { return x.player === 2 && x.stake === 12.5 && x.milestone === 10; }), JSON.stringify(v));
      check("waehrend des Speicherns: Knopf gesperrt 'Speichere …'", $("#bc-save").disabled && /Speichere/.test($("#bc-save").textContent));
      await wait(500);
      check("Antwort: 2 gespeichert -> aus dem Schein, '2 Wetten gespeichert ✓'", $$(".bc-item").length === 1 && /2 Wetten gespeichert ✓/.test(txt("#bc-msg")), txt("#bc-msg"));
      check("fehlgeschlagene Zeile bleibt im Schein mit roter Meldung und Grund", /Carla Gamma 25\+: nicht gespeichert – Testfehler/.test(txt("#bc-msg")) && row(3, 25).classList.contains("bc-sel"), txt("#bc-msg"));
      check("gespeicherte Wetten jetzt '✓ gesetzt' (gesperrt)", row(1, 20).classList.contains("bc-set") && row(2, 10).classList.contains("bc-set") && row(2, 15).classList.contains("bc-locked"));
      render({}); render({}); await wait(100);
      check("dieselbe Antwort bei jedem weiteren Rerun wird nicht noch einmal angewendet (Meldung/Schein unveraendert, nichts neu gesendet)", $$(".bc-item").length === 1 && sent.length === 1);
      click($("#bc-clear"));
      check("Leeren verwirft den Schein", $$(".bc-item").length === 0 && $$(".bc-sel").length === 0);
      await wait(150);
      check("nach dem Leeren: Rahmenhoehe wieder wie am Anfang (schmale Zeile), entspricht dem Inhalt", Math.abs(lastHeight() - h0) <= 2 && Math.abs(lastHeight() - contentH()) <= 2, h0 + " / " + lastHeight());
      A.locked = { "4": 10 }; render({}); await wait(80);
      click(row(1, 20)); click(row(2, 10)); click(row(3, 25)); await wait(150);
      var hMany = lastHeight(); $("#bc-def").value = "10"; var many = $$(".bc-item").length; $("#bc-clear").click(); await wait(150);
      check("Hoehe folgt dem Schein auch bei mehreren Kaertchen (3 Wetten hoeher als leer)", many === 3 && hMany > h0 && Math.abs(hMany - h0) < 400, h0 + " -> " + hMany);
    } catch (e) { out.push("FAIL Ausnahme im Test: " + e + " " + (e.stack || "")); }
    var pre = document.createElement("pre"); pre.id = "autotest"; pre.textContent = out.join("\n") + "\nENDE"; document.body.appendChild(pre);
  }
})();
</script>
"""

def build(autotest: bool) -> str:
    html = (ROOT / "ui" / "components" / "bet_cards" / "index.html").read_text(encoding="utf-8")
    drv = DRIVER % {"args": json.dumps(ARGS), "args2": json.dumps({**ARGS, "html": CARDS2}), "auto": "true" if autotest else "false"}
    return html.replace("</body>", drv + "</body>")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    auto = "--autotest" in sys.argv
    if auto:
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not Path(chrome).exists():
            print("Google Chrome nicht gefunden: bitte ohne --autotest starten und die Datei im Browser oeffnen."); sys.exit(2)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.html"; f.write_text(build(True), encoding="utf-8")
            r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--window-size=1300,1000", "--virtual-time-budget=15000", "--dump-dom", f"file://{f}"], capture_output=True, text=True, timeout=120)
        import re, html as H
        m = re.search(r'<pre id="autotest">(.*?)</pre>', r.stdout, re.S)
        if not m:
            print("Kein Ergebnis aus dem Browser.\n", r.stderr[-500:]); sys.exit(1)
        res = H.unescape(m.group(1)); print(res)
        sys.exit(0 if "FAIL" not in res else 1)
    out = Path(args[0] if args else "/tmp/nbaedge_wettschein_vorschau.html")
    out.write_text(build(False), encoding="utf-8")
    print(out)

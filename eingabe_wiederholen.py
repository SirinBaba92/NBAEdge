"""
Eingaben aus einem Terminalprotokoll von eingabe.py wieder einspielen, bis zur Zusammenfassung, dann uebergibt das Skript an dich.

Start:  venv/bin/python eingabe_wiederholen.py eingabe_protokoll.txt 2 [--korrektur "Quote Tre Johnson 13+=2.07"]
        (2 = die Spielnummer, die im Protokoll bei "Nummer wählen" getippt wurde)

Das Skript liest NUR das Protokoll (Datei wird nie veraendert), findet das Spiel, stellt dieselben Fragen wie eingabe.py und beantwortet sie mit den
Eingaben aus dem Protokoll (inklusive Leereingaben und Fehleingaben). Die letzte Frage "Speichern?" beantwortet es NICHT: dort steht das Terminal wieder
dir zur Verfuegung (Enter = speichern, n = verwerfen, z = aendern, q = beenden). Gespeichert wird also erst, wenn du selbst bestaetigst.

Regeln beim Einspielen
- Jede Frage wird mit der Frage im Protokoll verglichen (ohne die Vorgaben in eckigen Klammern). Weicht sie ab, bricht das Skript ab, ohne etwas zu speichern.
  Ausnahme: Rueckfragen 'Gespeicherte ... passen nicht ...' (haengen vom gespeicherten Stand ab) werden uebersprungen, wenn sie jetzt nicht mehr gestellt werden.
- Ein 'Speichern?' mit Enter, auf das im Protokoll eine Fehlermeldung folgte (z. B. Limit), wird nicht eingespielt. 'z' (aendern) wird eingespielt.
- Steht im Protokoll nach einem 'Speichern?' schon 'Gespeichert.', 'Nichts geändert.' oder 'Entfernt.', wird das Spiel NICHT erneut eingespielt (--trotzdem hebt das auf).
- --korrektur "Frage=Antwort" ersetzt die Antwort auf genau diese Frage (Text vor den eckigen Klammern); mehrfach moeglich.
- --bestaetigen (nur zum Testen): beantwortet auch die letzte 'Speichern?'-Frage mit Enter; nur erlaubt, wenn NBAEDGE_TRACKING_DIR gesetzt ist (Temp-Umgebung).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import eingabe as ei
from data import pre_match_store as store

PROMPT_RE = re.compile(r"^(Quote |Spread-Linie |Weitere (?:Spread|Team-Total)-Linie|Total-Linie|Team-Total-Linie|Anzahl |Start-Linie |End-Linie |Nummer|Speichern\?|Gespeicherte |"
                       r"[^:]+-Spieler \d+ von \d+: Name)")
BRACKET_RE = re.compile(r"\s*\[[^\]]*\]")
SUCCESS = ("Gespeichert.", "Nichts geändert.", "Entfernt.")


class ReplayError(Exception):
    pass


def norm(prompt: str) -> str:
    """Frage ohne Vorgaben in eckigen Klammern, ohne Doppelpunkt am Ende, einfache Leerzeichen."""
    p = BRACKET_RE.sub("", prompt.replace("\u00a0", " ")).strip()
    p = " ".join(p.rstrip(":").split())
    return "Speichern?" if p.startswith("Speichern?") else p


def split_prompt(line: str) -> tuple[str, str]:
    s = line.rstrip("\r\n")
    if s.endswith(":"):
        return s[:-1], ""
    i = s.rfind(": ")
    return s[:i], s[i + 2:].strip()


def parse_protocol(text: str, game_no: int) -> dict:
    """Findet das Spiel (Nummer wie bei 'Nummer wählen' getippt; bei Wiederholung das letzte) und liefert
    {'header': ..., 'steps': [(Frage-normalisiert, Antwort)], 'final_pending': bool, 'saved_in_protocol': bool}."""
    lines = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sel, starts = None, []                                       # (Zeile des Kopfes, getippte Spielnummer)
    for i, ln in enumerate(lines):
        if ln.startswith("Nummer wählen"):
            sel = split_prompt(ln)[1]
        elif ln.startswith("=== "):
            starts.append((i, sel))
    mine = [(i, s) for i, s in starts if s is not None and s.strip() == str(game_no)]
    if not mine:
        raise ReplayError(f"Im Protokoll gibt es kein Spiel mit der Nummer {game_no} (gefunden: {[s for _i, s in starts]}).")
    i0 = mine[-1][0]
    end = next((j for j in range(i0 + 1, len(lines)) if lines[j].startswith("Spiele (noch nicht begonnen") or lines[j].startswith("=== ")), len(lines))
    header = lines[i0]
    steps, k, saved = [], i0 + 1, False
    seg = lines[i0 + 1:end]
    # Eingabe-Zeilen erkennen
    items = []
    for j, ln in enumerate(seg):
        if ln.startswith(" ") or not PROMPT_RE.match(ln):
            continue
        items.append((j, *split_prompt(ln)))
    final_pending = False
    for idx, (j, prompt, ans) in enumerate(items):
        if norm(prompt) != "Speichern?" and not prompt.startswith("Speichern?"):
            steps.append((norm(prompt), ans))
            continue
        # Folgezeile bestimmt, was aus dieser Bestaetigung wurde
        nxt = next((x for x in seg[j + 1:] if x.strip()), None)
        if ans.strip().lower() == "z":
            steps.append(("Speichern?", "z"))
        elif ans.strip().lower() == "n":
            steps.append(("Speichern?", "n"))
        elif nxt is None or (idx == len(items) - 1 and (nxt.startswith("Nummer wählen") or nxt.startswith("Spiele ("))):
            final_pending = True
            steps.append(("Speichern?", ans))
        elif nxt.strip() in SUCCESS or nxt.strip().startswith("Gespeichert"):
            saved = True
            steps.append(("Speichern?", ans))
        elif nxt.startswith("  "):
            continue                                              # Speichern abgelehnt (Fehlermeldung): nicht einspielen
        else:
            steps.append(("Speichern?", ans))
    return {"header": header, "steps": steps, "final_pending": final_pending, "saved_in_protocol": saved}


class ReplayReader:
    """read(prompt) fuer ei.Console: spielt die Protokoll-Antworten ein, uebergibt an die Tastatur bei der letzten Bestaetigung."""

    def __init__(self, steps, corrections=None, confirm=False, real=input, write=print, final_pending=True):
        self.steps, self.i = list(steps), 0
        self.corr = {norm(k): v for k, v in (corrections or {}).items()}
        self.used_corr: set = set()
        self.confirm, self.real, self.write = confirm, real, write
        self.handover = False
        self.final_pending = final_pending

    def __call__(self, prompt: str) -> str:
        if self.handover:
            return self.real(prompt)
        want_n = norm(prompt)
        while self.i < len(self.steps) and self.steps[self.i][0].startswith("Gespeicherte ") and not want_n.startswith("Gespeicherte "):
            self.write(f"  (Protokoll-Rückfrage übersprungen, wird jetzt nicht mehr gestellt: {self.steps[self.i][0][:70]}…)")
            self.i += 1
        last = self.i == len(self.steps) - 1 and self.final_pending and self.steps[self.i][0] == "Speichern?"
        if self.i >= len(self.steps) or (last and want_n == "Speichern?"):
            if want_n == "Speichern?":
                self.handover = True
                if self.confirm:
                    self.write(prompt + "(automatisch bestätigt)")
                    return ""
                self.write("")
                self.write("── Eingaben eingespielt. Ab hier tippst DU: Enter = speichern, n = verwerfen, z = ändern, q = beenden. ──")
                return self.real(prompt)
            raise ReplayError(f"Das Protokoll ist zu Ende, aber das Skript fragt noch: {prompt.strip()!r}")
        exp_n, ans = self.steps[self.i]
        if exp_n != want_n:
            raise ReplayError(f"Abweichung bei Protokollschritt {self.i + 1}: erwartet „{exp_n}“, gestellt „{want_n}“. Es wurde nichts gespeichert.")
        if want_n in self.corr:
            self.write(f"{prompt}{ans}   ← Korrektur: {self.corr[want_n]}")
            ans = self.corr[want_n]
            self.used_corr.add(want_n)
        else:
            self.write(f"{prompt}{ans}")
        self.i += 1
        return ans


def run(path: Path, game_no: int, corrections: dict, confirm: bool = False, force: bool = False, real=input, write=print, games=None, now_fn=None) -> int:
    if confirm and not __import__("os").environ.get("NBAEDGE_TRACKING_DIR"):
        write("--bestaetigen ist nur mit gesetztem NBAEDGE_TRACKING_DIR erlaubt (Temp-Umgebung). Abbruch, nichts gespeichert.")
        return 2
    try:
        proto = parse_protocol(Path(path).read_text(encoding="utf-8", errors="replace"), game_no)
    except (ReplayError, OSError) as e:
        write(f"Protokoll nicht lesbar: {e}")
        return 2
    m = re.match(r"^=== (.+?) – (.+?) · ", proto["header"])
    if not m:
        write(f"Kopfzeile des Spiels nicht erkannt: {proto['header']!r}")
        return 2
    home, away = m.group(1), m.group(2)
    if proto["saved_in_protocol"] and not force:
        write("Laut Protokoll wurde dieses Spiel schon gespeichert. Zur Sicherheit nicht erneut eingespielt (--trotzdem überschreibt die Sperre).")
        return 2
    kw = {"now": now_fn()} if now_fn else {}
    lst = ei.list_games(games=games, **kw)
    g = next((x for x in lst if x["home"] == home and x["away"] == away), None)
    if g is None:
        write(f"Das Spiel {home} – {away} ist nicht (mehr) in der Spieleliste (begonnen, beendet oder nicht im Zwischenspeicher).")
        return 2
    rr = ReplayReader(proto["steps"], corrections, confirm=confirm, real=real, write=write, final_pending=proto["final_pending"])
    con = ei.Console(read=rr, write=write)
    write(f"Spiele ein: {home} – {away}  ({len(proto['steps'])} Protokollschritte" + (", letzte Bestätigung übergibt an dich)" if proto["final_pending"] else ")"))
    try:
        res = ei.run_game(con, g, **({"now_fn": now_fn} if now_fn else {}))
    except ReplayError as e:
        write(f"\nABBRUCH: {e}")
        return 3
    except ei.Quit:
        write("Beendet. Es wurde nichts gespeichert, was du nicht bestätigt hast.")
        return 0
    unused = set(rr.corr) - rr.used_corr
    if unused:
        write(f"Hinweis: Korrektur nicht angewendet (Frage kam nicht vor): {sorted(unused)}")
    write({"saved": "Fertig: gespeichert.", "discarded": "Verworfen, nichts gespeichert.", "unchanged": "Nichts geändert."}[res])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Eingaben aus einem eingabe.py-Protokoll wieder einspielen (speichert erst nach deiner Bestätigung).")
    ap.add_argument("protokoll")
    ap.add_argument("spielnummer", type=int)
    ap.add_argument("--korrektur", action="append", default=[], metavar="FRAGE=ANTWORT")
    ap.add_argument("--bestaetigen", action="store_true", help="nur Temp-Umgebung: letzte Bestätigung automatisch")
    ap.add_argument("--trotzdem", action="store_true", help="auch einspielen, wenn das Protokoll schon 'Gespeichert.' zeigt")
    a = ap.parse_args(argv)
    corr = {}
    for c in a.korrektur:
        if "=" not in c:
            print(f"--korrektur erwartet FRAGE=ANTWORT, bekam: {c!r}")
            return 2
        k, v = c.rsplit("=", 1)
        corr[k.strip()] = v.strip()
    return run(Path(a.protokoll), a.spielnummer, corr, confirm=a.bestaetigen, force=a.trotzdem)


if __name__ == "__main__":
    sys.exit(main())

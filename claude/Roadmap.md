# NBAEdge Roadmap (Übersicht)

Stand: Do 5.11.2026, 22:00. Diese Datei enthält nur die gemeinsamen Regeln, die Phasenübersicht und die Konventionen. Die Aufgaben, Zahlen und Details stehen in den Phasen-Dateien. Frühere Details: Roadmap_Archiv.md (bis 1.11.) und Roadmap_Archiv_2.md (2. bis 5.11.); beide werden nicht mehr beschrieben und nur bei Bedarf gelesen.

## Phasen (jede Phase hat ihre eigene Datei)
| Phase | Thema | Datei | Wann |
|---|---|---|---|
| A | Betrieb: Tagesroutine, Betano-Automatik, Aufräumen, Tests, Backup | claude/Phase_A.md | laufend, täglich |
| B | Spielerprognosen: Verlängerung, zweite Vorsaison, Ausfallbehandlung, Rollenwechsel | claude/Phase_B.md | ab 9.11. |
| C | Team-Märkte: team-2, Tempo, Moneyline, Spread/Total/Team Total, Betano-Marge, Rundung | claude/Phase_C.md | ab 5.11. (3.5), Rest ab 16.11. |
| D | App und Oberfläche: Tab-Punkte, Browser-Test, Verletzungsberichte | claude/Phase_D.md | wenn Zeit |
| E | Entscheidungen im Dezember (ca. 300 Spiele) | claude/Phase_E.md | ab Dezember |
| F | Januar und später, optionale Erweiterungen | claude/Phase_F.md | ab Januar |

## Konventionen für die Phasen-Sitzungen
- Jede Sitzung liest zuerst diese Datei (Regeln) und dann ihre Phasen-Datei. Archive nur bei Bedarf.
- Eine Sitzung schreibt NUR ihre eigene Phasen-Datei. Roadmap.md wird nur im Planungsgespräch oder auf ausdrücklichen Wunsch von Baran geändert.
- Jede Phasen-Datei hat am Ende den Abschnitt "Archiv Phase X": dort kommen neue Details und Messzahlen hin. Oben stehen nur offene Punkte und Ein-Satz-Ergebnisse.
- Was eine Sitzung bei einer anderen Phase vermutet oder braucht, schreibt sie Baran als Hinweis, nicht in die andere Datei.
- Neue Punkte, die in keine Phase passen, nennt die Sitzung Baran; im Planungsgespräch werden sie eingeordnet.
- Die Startnachricht steht am Ende jeder Phasen-Datei.

## Arbeitsregeln (gelten in allen Phasen)
- Antworte auf Deutsch, einfach und kurz. Immer nur eine Frage und ein Schritt auf einmal.
- Zu jeder Frage schreibt Claude seine Empfehlung dazu. Wenn Baran "du entscheidest" oder "weiter" sagt, gilt die Empfehlung.
- Erst alles besprechen, dann ändern bzw. der Claude-Code-Prompt.
- Jeder Claude-Code-Prompt endet mit: "Kein Commit, keine Pushes, kein Backup. Das mache ich selbst mit nbabackup."
- Es laufen nur neue oder direkt betroffene Tests. Rückmeldung höchstens 15 Zeilen.
- Gesamttestlauf macht Baran selbst (ca. 11 bis 18 Minuten, Claude Code währenddessen nicht nutzen):
  `cd ~/Desktop/NBAEdge && for t in tests/test_*.py; do echo "$(basename $t .py) FAIL=$(venv/bin/python $t 2>&1 | grep -c '^FAIL')"; done | grep -v "FAIL=0"; echo FERTIG`
- Frag Baran nie nach nbabackup, das macht er selbst.
- Jeder Punkt: Daten beschaffen -> testen -> entscheiden. Positiv = behalten. Negativ = ausführlich ins Archiv der Phase, in der Aufräumliste (Phase A) eine Zeile.
- "Festgelegt" heißt nur: was und wann. Ob etwas etwas bringt, entscheiden wir nach dem Test.
- Ziel: verlässliche, kalibrierte Prognosen (nicht Betano schlagen).
- Claude pflegt seine Phasen-Datei nach jedem Schritt und sagt ehrlich, was geprüft ist und was nicht.

## Festlegungen, die gelten
- Betano-Abruf kurz vor Spielbeginn, Wetten danach (Automatisierung stündlich, siehe Phase A).
- Abruf-Prompts nie gleichzeitig. Downloads nur tagsüber, nie nachts während der Aufzeichnung.
- Keine Wetten auf Rebounds, Assists, Dreier.
- Tab Spieler: orange Balken = Modell roh; grünes ✓ und Mindestquote nur für Starter mit mindestens 10 Spielen und Roh-Chance ab 80 %.
- Fraglich-Warnung auf den Karten wird nicht umgesetzt.
- Kein Backup für NBAEdge_pbp (Entscheidung 30.10.).
- Hand-Linien bleiben immer unberührt; ein erneuter Handabruf holt Betano-Änderungen nach; kein Knopf "Prognose erstellen" mehr, sobald ein Spiel eine Prognose hat.
- Prognosen für alle Spiele vor dem ersten Anpfiff des Spieltags erstellen (Baran 4.11.: dann alle 14 Spiele gewertet).
- Das Modell rechnet in den Spielerkarten seit 29.10. ohne Ausfälle (Regel 94); der Informationswert-Test zeigt bisher keinen belegten Zusatz zu Betano.

## Stand der Zahlen (5.11., für alle Phasen)
- 108 Spiele in der Auswertung (14 Spieltage, 11258 Zeilen); Informationswert-Test 13 Tage, 91 Spiele, 1153 Spieler-Tage: Brier Betano 0,2194, Modell roh 0,2368, Teamabgleich 0,2423.
- Gesamttestlauf 5.11. grün. Letztes Backup durch die Morgenroutine: 69f89d5 (5.11.); nbabackup nach dem Gesamtlauf am 5.11. durch Baran gemacht (Commit nicht gesendet).

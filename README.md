# eduexaminer-exchange (funktionsfähige Fassung)

TCExam-XLSX → eduExaminer-EXZ, **mit Kommazahl-Punkten**.

Der reguläre CSV/XLSX-Import von eduExaminer akzeptiert nur ganzzahlige Punkte.
Über das proprietäre EXZ-Format gehen Kommazahlen. Dieses Projekt macht daraus
einen wiederholbaren Workflow statt eines Notebook-Einzelfalls.

Aufbauend auf [mckoh/eduexaminer-exchange](https://github.com/mckoh/eduexaminer-exchange).

> **Kein Prüfungsmaterial im Repository.** `input/` und `output/` sind per
> `.gitignore` ausgeschlossen. Was mitversioniert wird, liegt in `vorlage/` und
> enthält nur Platzhalter. Eigene Fragendateien und Exporte bitte dort ablegen,
> wo Git sie nicht sieht.

## Die drei Importwege

eduExaminer ist die Bildungsvariante von **bizExaminer** (BizDevelop Informationstechnologie GmbH).
Laut Support-Doku gibt es fünf Importwege: MS Word, CSV, bizExaminer-Datei (`.exz`),
Moodle XML und QTI/QML.

| Weg | Kommazahlen | Stand |
|---|---|---|
| **EXZ** (`rescore` / `build`) | ja | gegen echten Export **verifiziert** |
| QTI 1.2 (`qti`) | ja — `<setvar>` ist dezimalfähig | offiziell dokumentiert, Import ungetestet |
| CSV/XLSX | nein, nur ganzzahlig | — |

**Der EXZ-Weg ist der sichere.** Das Format wurde gegen einen echten Export
abgeglichen: der Generator erzeugt das `presentation`-XML **bitgenau identisch**
zu dem, was eduExaminer selbst schreibt (46/46 Fragen).

## Das EXZ-Format

```
export.exz  ──zlib──▶  JSON  ──base64──▶  XML
                         │                 ├─ <presentation>   Frage + Antworten
                         │                 └─ <resprocessing>  Punkte  ◀── darum geht's
                         └─ topics.questions[i].revisions[0]
```

- Container: rohes **zlib**, kein ZIP
- Top-Level: `type` · `topics` · `instructions`
- Frage: `id` · `exm_question_types_id` (13 = Multiple Response) · `title` ("Frage 01") ·
  `instruction` · `itemfeedback` · `tags` · `comments` · `revisions` ·
  `question_instructions` · `images` · `options`
- Revision: `presentation` · `resprocessing` · `feedback` ·
  `exm_question_type_instructions_id` · `presentationType` · `language` · `editmode`

Eigenheiten des XML-Dialekts, die eingehalten werden müssen:

- Zeilenumbruch nach der XML-Deklaration, sonst alles auf einer Zeile
- `mattext`-CDATA enthält **Klartext**, kein `<p>...</p>`
- `resprocessing` nutzt `action="Set"` (nicht `"Add"`) und **zwei** `respcondition`
  pro Antwort: angekreuzt → Punkte, nicht angekreuzt → 0
- `<global>` mit `mrAnswersType` · `evaluationType` · `allowNegativeOutcome`
- kein `<settings>`-Block, kein `rcardinality`

## Punkteregeln

Pro Antwortoption kennt das EXZ **vier** Faelle, weil je Antwort zwei
`respcondition`-Blöcke existieren (angekreuzt / nicht angekreuzt):

| | angekreuzt | nicht angekreuzt |
|---|---|---|
| richtige Antwort | `correct` | `correct_unticked` |
| falsche Antwort | `wrong` | `wrong_unticked` |

### `--scheme balanced` (Standard)

Nur das Ankreuzen wird bewertet, die Nicht-Ankreuz-Fälle bleiben 0.

```
correct = + TOTAL / k        wrong = − TOTAL / (n − k)
```

**TOTAL ist standardmäßig die Zahl der Antwortmöglichkeiten** — ein Punkt je
Antwort. Eine Frage mit 4 Antworten ist 4 Punkte wert, eine mit 6 Antworten 6.
Eine feste Punktzahl erzwingt `--total`.

| k | n=4 (max 4) | n=6 (max 6) |
|---|---|---|
| 1 | +4 / −1,333 | +6 / −1,2 |
| 2 | +2 / −2 | +3 / −1,5 |
| 3 | +1,333 / −4 | +2 / −2 |
| 4 | — | +1,5 / −3 |
| 5 | — | +1,2 / −6 |

Erwartungswert beim Raten = 0, Leerabgabe = 0 — in beiden Fällen.

Bei n=6 gehen **alle** Werte exakt auf. Nur n=4 mit k=3 hat einen Rest:
3 × 1,333 = 3,999 statt 4.

Die Regel gewichtet Fragen nach der Zahl der Einzelurteile, die sie verlangen.
In einer Prüfung mit gemischten Fragen zählt eine 6er-Frage damit das
1,5-Fache einer 4er-Frage.

### `--scheme symmetric`

Jede der n Optionen ist ein eigenes Ja/Nein-Urteil. Ein richtiges Urteil
bringt `PLUS`, ein falsches kostet `MINUS` — unabhängig davon, ob es durch
Ankreuzen oder durch Nicht-Ankreuzen zustande kommt.

```
correct = wrong_unticked = + PLUS      (Urteil richtig)
wrong = correct_unticked = − MINUS     (Urteil falsch)
```

Damit sind **Maximum und Minimum unabhängig von k**:

```
Maximum = n × PLUS        Minimum = − n × MINUS
```

Mit `PLUS=1`, `MINUS=0,5` und n=4 also **max +4, min −2** bei jeder Frage,
und ohne jeden Rundungsrest. Standardwerte: `PLUS = TOTAL / n`, `MINUS = PLUS / 2`.

Preis dieser Symmetrie: eine **Leerabgabe** ist nicht mehr neutral, weil
korrektes Nicht-Ankreuzen belohnt wird. Bei n=4, PLUS=1, MINUS=0,5:

| k | Leerabgabe | Raten (50 %) |
|---|---|---|
| 1 | +2,5 von 4 | +1 |
| 2 | +1 von 4 | +1 |
| 3 | −0,5 von 4 | +1 |

Wer bei einer k=1-Frage nichts ankreuzt, bekommt also 2,5 von 4 Punkten.
Das lässt sich über `--minus` verschieben: mit `--plus 1 --minus 1` wird die
Leerabgabe bei k=2 exakt 0 (Maximum +4, Minimum −4).

`points` rechnet Maximum, Minimum, Leerabgabe und Ratenerwartung je Frage vor:

```bash
python -m exz points fragen.xlsx --scheme symmetric
```

`k` wird aus dem Excel bzw. aus dem EXZ selbst gezählt — es braucht keine
K1/K2/K3-Spalte.

## Fragetypen

| Excel-Wert | intern | eduExaminer | `exm_question_types_id` | Punkte |
|---|---|---|---|---|
| `multiple` | `multiple` | Multiple Response | **13** | Formel, Standard max 4 |
| `freeanswer` · `essay` | `essay` | Discursive Writing | **2** | je Datei einstellbar, Voreinstellung **4** |

Beide Typ-IDs stammen aus echten Exporten, nicht aus Vermutungen.

### Offene Fragen (Typ 2)

Der Aufbau unterscheidet sich deutlich von Multiple Choice:

- **kein Antwort-Element** — kein `<response_str>`, kein `<render_fib>`, gar nichts
- `<material>` **ohne** `label="question"`
- `<activateTinyMCE>true</activateTinyMCE>` schaltet den Formatiereditor frei
- `<global>` enthält **nur** `allowNegativeOutcome`, kein `mrAnswersType`/`evaluationType`
- genau **eine** `<respcondition title="Scored">` mit `<other/>` als Bedingung und
  der erreichbaren Punktzahl

Korrigiert wird von Hand, deshalb gibt es keine Antwortbedingungen.

Die Punktzahl ist **keine Konstante**: sie richtet sich nach dem Umfang der
erwarteten Antwort (üblich sind 4 bis 10) und gilt jeweils für **alle** offenen
Fragen einer Datei. Pools mit sehr unterschiedlich umfangreichen offenen Fragen
werden daher in mehreren Dateien gebaut, je eine pro Punktzahl.

**`build` klont den Prototyp aus der Vorlage** — pro Fragetyp die erste passende
Frage, erkannt am `presentation`-XML (`<response_lid>` → Multiple Choice,
`<response_str>` → offen). Dadurch müssen weder die interne `exm_question_types_id`
noch die übrigen Felder erraten werden. Fehlt in der Vorlage ein benötigter Typ,
bricht `build` mit einer Anleitung ab, statt etwas Falsches zu erzeugen.

## Excel-Layout

Zwei Layouts werden **automatisch erkannt** — gesucht wird die Spalte mit den
Typangaben, der Fragetext steht links davon:

```
TCExam-Vorlage : A=Nr  B=Frage  C=Typ  D/E F/G H/I ...  (Antwort, true/false)
Kurzform       : A=Frage  B=Typ                          (offene Fragen)
```

Eine Kopfzeile darf vorhanden sein oder fehlen; beide Fragetypen dürfen in
derselben Datei gemischt vorkommen.

Die true/false-Spalten werden typtolerant gelesen — **beide Varianten funktionieren**:

- echte Booleans (deutsches Excel zeigt `WAHR`/`FALSCH`, openpyxl liefert `True`/`False`)
- Textwerte `true` / `false`
- zusätzlich: `1`/`0`, `x`, `ja`/`nein`, `wahr`/`falsch`, `richtig`/`falsch`, leer = false

Ein unbekannter Wert bricht mit Zeilen- und Spaltenangabe ab, statt still `false`
anzunehmen. Geschützte Leerzeichen, Mehrfach-Leerzeichen und CRLF werden bereinigt,
Unicode auf NFC normalisiert.

## Installation

```bash
pip install -r requirements.txt
```

## Weboberfläche: `streamlit run app.py`

Für alle, die nichts auf der Platte haben wollen: Excel hochladen, Punkte
einstellen, fertige Datei herunterladen.

```bash
pip install -r requirements-app.txt
streamlit run app.py
```

Oder per Doppelklick auf `App-starten.bat` — die richtet beim ersten Start
alles ein und öffnet den Browser.

Einstellbar in der App: **Punkte je offener Frage** (Voreinstellung 4, je nach Umfang anzupassen). Die
Multiple-Choice-Bewertung steht fest und wird nur angezeigt; Maximalpunkte,
Nachkommastellen und Minuspunkte liegen hinter „Erweitert".

Die App zeigt vor dem Download eine Vorschau mit allen Fragen und den
errechneten Punkten — dort fallen Fragen ohne richtige Antwort sofort auf.

## Schnellweg: `Excel-zu-EXZ.bat`

Excel-Datei auf die BAT ziehen — fertig. Die `.exz` landet **im selben Ordner
wie die Excel-Datei**, mit demselben Namen. Keine Rückfragen, keine Dialoge:
bei Erfolg schließt sich das Fenster von selbst, bei einem Fehler bleibt es
offen und nennt die Ursache.

Python wird selbst gesucht, `openpyxl` bei Bedarf nachinstalliert, die
Zwischendateien landen in `%TEMP%`.

Einstellbar oben in der Datei:

| Variable | Standard | Bedeutung |
|---|---|---|
| `TOTAL` | `4` | max. Punkte je Multiple-Choice-Frage |
| `ESSAY` | `4` | Punkte je offener Frage, je nach Umfang anzupassen |
| `DECIMALS` | `3` | Nachkommastellen |
| `TEMPLATE` | `vorlage\struktur-vorlage.exz` | Strukturvorlage, beide Fragetypen |
| `SHEET` | leer | Tabellenblatt; leer = erstes Blatt |
| `NEGATIVE` | leer (aus) | auf `--negative` setzen für Minuspunkte |

## Verwendung (Kommandozeile)

### `rescore` — Punkte in einem bestehenden EXZ neu setzen (empfohlen)

Der risikoärmste Weg: Fragen bleiben, wie sie sind, nur die Zahlen ändern sich.

```bash
python -m exz rescore mein-export.exz --total 4 -o output/export_4punkte.exz
```

Ersetzt **ausschließlich** die Werte in `<setvar action="Set">`. Struktur, Whitespace,
Feedback-Verweise, IDs und alle übrigen Felder bleiben unberührt. Welche Antwort
richtig ist, wird aus der Datei selbst gelesen (positiver Punktwert = richtig).

Für eine ganzzahlige 12-Punkte-Skala: `--total 12 --decimals 0`

Minuspunkte umschalten, ohne sonst etwas zu ändern: `--negative yes` bzw. `no`
(Standard `keep` lässt den Wert, wie er ist).

### `inspect` — EXZ analysieren

```bash
python -m exz inspect mein-export.exz -o output/inspect
```

Zeigt Container-Typ, JSON-Struktur und alle Base64-XML-Felder, markiert das
Bewertungsfeld und legt jedes dekodierte XML einzeln ab.

### `build` — EXZ komplett aus dem Excel neu bauen

```bash
python -m exz build fragen.xlsx --template vorlage/struktur-vorlage.exz -o import.exz
```

Ohne `--template` werden nur die XML-Dateien nach `output/xml/` geschrieben.

Optionen: `--total` · `--decimals` · `--scheme balanced|symmetric` · `--plus` ·
`--minus` · `--negative` · `--shuffle` · `--score-field` · `--presentation-field` ·
`--title-format "Frage {nr:02d}"`

Beispiel für max +4 / min −2 mit aktivierten Minuspunkten:

```bash
python -m exz build fragen.xlsx --template vorlage/struktur-vorlage.exz --scheme symmetric --negative -o symmetrisch.exz
```

### `points` — Punkte vorrechnen (braucht kein EXZ)

```bash
python -m exz points fragen.xlsx --csv punkte.csv
```

### `qti` — QTI-1.2-Paket bauen

```bash
python -m exz qti fragen.xlsx --title "Meine Lehrveranstaltung"
```

Erzeugt `output/qti/questions.xml` und `output/qti_import.zip` (XML + `imsmanifest.xml`).
Import: Autor-Rolle → *Topics Questions* → **import** → Reiter **„QTI and QML import"**.

Optionen: `--cardinality Multiple|Single|auto` · `--zip ""` · `--no-manifest`

### `repack` — Round-Trip-Test

```bash
python -m exz repack mein-export.exz
```

## Wie `build` arbeitet

Die **erste Frage der Vorlage dient als Prototyp**. Pro Excel-Zeile wird sie kopiert,
IDs deterministisch neu vergeben (uuid5 aus der Fragennummer — gleiche Eingabe,
gleiche IDs), Titel gesetzt und `presentation` + `resprocessing` ersetzt. Alle übrigen
Felder bleiben unverändert.

Das ist bewusst konservativ: was eduExaminer sonst noch im Revisionsobjekt erwartet,
muss nicht bekannt sein, es wird einfach mitgeschleppt.

## Dateien

| | |
|---|---|
| `exz/exzfile.py` | EXZ-Container lesen/schreiben (zlib · zip · gzip · raw), Base64-Helfer, Baumsuche |
| `exz/excel.py` | XLSX einlesen, tolerante true/false-Erkennung, Textbereinigung |
| `exz/scoring.py` | Punkteformeln, beide Schemata (`Decimal`, kein Float-Rauschen) |
| `exz/qti.py` | XML im eduExaminer-Dialekt: `<presentation>` und `<resprocessing>` |
| `exz/rescore.py` | Punkte in vorhandenem XML ersetzen, minimalinvasiv |
| `exz/qtipkg.py` | vollständiges QTI-1.2-Paket (`questestinterop`) + ZIP mit Manifest |
| `exz/api.py` | gemeinsamer Kern: Excel → EXZ als Bytes, ohne Dateisystem und ohne `print` |
| `app.py` | Streamlit-Oberfläche (Upload → Download) |
| `exz/__main__.py` | CLI: `inspect` · `points` · `qti` · `build` · `rescore` · `repack` |
| `Excel-zu-EXZ.bat` | Drag-and-Drop-Weg für den Regelfall |
| `paket/START-HIER.txt` | Anleitung, die ins Weitergabe-ZIP wandert |
| `main.ipynb` | derselbe Workflow als Notebook |
| `tools_template.py` | baut `vorlage/struktur-vorlage.exz` (je ein Prototyp pro Fragetyp, inhaltsfrei) |
| `tools_package.py` | baut `output/eduExaminer-Import.zip` zur Weitergabe an Kolleg:innen |
| `tools_chart.py` | Punkteverlauf je Frage als PNG (`python tools_chart.py`) |
| `tools_make_fake_template.py` | synthetisches EXZ für Tests ohne echtes Export-File |

## Status

| Teil | Stand |
|---|---|
| Excel-Import, beide true/false-Varianten | verifiziert, 46 Fragen |
| Punkteberechnung | verifiziert gegen die Vorgabe |
| EXZ lesen/schreiben, Round-Trip | verifiziert am echten Export |
| `<presentation>`-XML | **bitgenau identisch zum echten Export, 46/46** |
| `<resprocessing>`-XML | **bitgenau identisch bei 40/46** — die 6 Abweichungen sind der K3-Befund unten |
| `rescore` minimalinvasiv | verifiziert: nur Zahlen geändert, Struktur bitgenau gleich |
| Fragen/Antworten Excel ↔ EXZ | 0 Abweichungen bei allen 46 Fragen |
| QTI-1.2-Paket | syntaktisch valide, Import ungetestet |
| Layout-Erkennung | verifiziert an beiden Arbeitsmappen |
| Offene Fragen (Typ 2) | `resprocessing` strukturell identisch zum echten Export |
| Eindeutige Fragen-IDs | verifiziert — vorher bekamen alle Klone dieselbe ID |
| Geerbte Bilder/Tags | werden beim Klonen entfernt |
| **EXZ-Import in eduExaminer** | **funktioniert — mit `neubau_4punkte.exz` bestätigt** |
| Schema `symmetric` | verifiziert: max +4, min −2 bei allen 46 Fragen, nur die Werte +1 und −0,5 |
| Negativwerte im Import | **offen** — kamen mit `allowNegativeOutcome=0` als 0 an; mit `=1` noch zu testen |

## Befund: K3-Malus im importierten Bestand

Der aktuelle Export rechnet auf 12 Punkte. Die Formel wird bei K1 und K2 eingehalten,
bei K3 nicht:

| | richtig | falsch (Datei) | falsch (Formel) |
|---|---|---|---|
| K1 (24 Fragen) | +12 | −4 | −4 ✓ |
| K2 (16 Fragen) | +6 | −6 | −6 ✓ |
| K3 (6 Fragen) | +4 | **−4** | **−12** ✗ |

Betroffen sind die Fragen **12, 16, 17, 20, 22, 25**. Die Struktur ist identisch,
nur der Zahlenwert weicht ab.

Vermutlich beim Hochskalieren übersehen: die Pluswerte wurden alle ×3 genommen
(4→12, 2→6, 1,333→4), bei den Minuswerten ebenso (−1,333→−4, −2→−6), nur
K3s −4 blieb −4 statt −12.

Auswirkung: Wer bei einer K3-Frage blind alle vier Antworten ankreuzt, bekommt
4+4+4−4 = **8 von 12 Punkten** ohne jedes Wissen. Mit −12 wären es 0.

Beide `rescore`-Läufe korrigieren das automatisch, weil sie die Formel neu anwenden.

## Minuspunkte (`allowNegativeOutcome`)

Der `<global>`-Block steuert drei Dinge, die den Einstellungen im *Options*-Tab
der Frage entsprechen:

| Tag | Wert im Export | Oberfläche |
|---|---|---|
| `mrAnswersType` | 1 | „Allow selection of multiple answers" |
| `evaluationType` | 1 | „Award points per answer" |
| `allowNegativeOutcome` | 0 | „Negative points possible: **No**" |

Mit `0` wird die Punktzahl **je Frage bei 0 abgeschnitten**. Das untergräbt die
Ratensperre teilweise: bei K1 bringt „alle vier ankreuzen" 4 − 3×1,333 = 0
(korrekt), aber „nur die drei falschen ankreuzen" gäbe −4 und wird auf 0
hochgezogen. Der Erwartungswert beim Raten liegt damit leicht **über** 0.

Wer die Balance exakt will, setzt `--negative` (bzw. in der BAT die Variable
`NEGATIVE`). Alternativ in der Oberfläche pro Frage auf „Negative points
possible: Yes" stellen — dasselbe Ergebnis, nur von Hand.

## Anmerkung zur Rundung

Bei K3 auf der 4-Punkte-Skala ergibt 3 × 1,333 = **3,999**, nicht 4. Auf drei
Nachkommastellen unvermeidbar; `--decimals 4` macht 3,9999 daraus. Auf der
12-Punkte-Skala tritt das Problem nicht auf — dort ist alles ganzzahlig.

## Bilder in Fragen

**Unterstützt.** Ein Bild, das in der Excel-Datei in der Zeile einer Frage
eingebettet ist, wandert mit in die EXZ-Datei. Der Anker entscheidet: openpyxl
liefert über `ws._images` zu jedem Bild die Zelle, an der es hängt — die Zeile
daraus bestimmt, zu welcher Frage es gehört.

Eine Frage darf **nur** aus einem Bild bestehen; eine Zeile mit Fragetyp, Bild
und leerer Textspalte wird nicht mehr übersprungen.

Am Frage-Objekt entsteht ein `images`-Eintrag:

```json
"questionresources/9/1.png": {
  "dataType": "exmimg",
  "filename_original": "zeile-10.png",
  "filename_new": "1.png",
  "type": "question",
  "dataID": 9,
  "resourcesCode": "af8c49fa5e",
  "mimeType": "image/png",
  "path": "questionresources/##question_id##/1.png",
  "data": "<base64>",
  "use_as_question_enclosure": 0,
  "print_with_testletter": 0,
  "download_in_question": 0
}
```

Im Fragetext steht die Referenz mit Platzhaltern, die eduExaminer beim Anzeigen
auflöst:

```html
<p><img src="##images_path##questionresources/##question_id##/1.png"
        width="700" height="387" alt="" /></p>
```

Details, die eingehalten werden:

- Schlüssel und `dataID` tragen die **endgültige** Frage-ID, deshalb werden die
  Bilder erst nach der ID-Vergabe angehängt
- `filename_new` ist über den ganzen Export eindeutig (fortlaufend gezählt)
- `resourcesCode` ist ein Hash der Bilddaten — gleiche Eingabe, gleiche Datei
- Bilder breiter als **700 px** werden proportional verkleinert
- ohne Bilder bleibt das erzeugte XML unverändert; die Bit-Gleichheit zu echten
  Exporten ist weiterhin geprüft (46/46)

## Quellen

- [Import questions: QTI and QML import](https://support.bizexaminer.com/article/import-questions-qti-and-qml-import/)
- [Import questions: bizExaminer file](https://support.bizexaminer.com/article/import-questions-bizexaminer-file/)
- [Export Questions and Question Topics](https://support.bizexaminer.com/article/export-questions-and-question-topics/)
- [Import questions (Übersicht)](https://support.bizexaminer.com/article/import-questions/)
- [eduExaminer | bizExaminer](https://www.bizexaminer.com/eduexaminer/)

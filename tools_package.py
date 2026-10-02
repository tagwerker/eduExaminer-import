"""Baut ein weitergabefaehiges ZIP fuer Kolleginnen und Kollegen.

    python tools_package.py [output/eduExaminer-Import.zip]

Enthalten ist alles, was auf einem fremden Windows-Rechner gebraucht wird -
ausser Python selbst. NICHT enthalten ist Pruefungsmaterial: die
Struktur-Vorlage wird auf eine einzige Platzhalterfrage reduziert, und die
Excel-Vorlage wird geleert.
"""
from __future__ import annotations

import base64
import copy
import io
import os
import re
import shutil
import sys
import zipfile

import openpyxl

from exz.exzfile import read_exz, write_exz, find_questions

SOURCE_EXZ = "vorlage/struktur-vorlage.exz"
SOURCE_XLSX = "vorlage/Fragen-Vorlage.xlsx"
PKG = "eduExaminer-Import"

PLACEHOLDER_PRESENTATION = """<?xml version="1.0"?>
<presentation><version downcompatible="1">1</version><material label="question">\
<mattext texttype="text/html"><![CDATA[Platzhalter]]></mattext></material>\
<response_lid ident="1"><render_choice shuffle="No">\
<response_label ident="A"><material><mattext texttype="text/html">\
<![CDATA[A]]></mattext></material></response_label>\
<response_label ident="B"><material><mattext texttype="text/html">\
<![CDATA[B]]></mattext></material></response_label>\
<response_label ident="C"><material><mattext texttype="text/html">\
<![CDATA[C]]></mattext></material></response_label>\
<response_label ident="D"><material><mattext texttype="text/html">\
<![CDATA[D]]></mattext></material></response_label>\
</render_choice></response_lid>
</presentation>
"""


def build_structure_template(dest: str) -> None:
    """Uebernimmt die bereits bereinigte Vorlage aus tools_template.py.

    Sie enthaelt je eine Platzhalterfrage pro Fragetyp (Multiple Choice und
    offene Frage) und kein Pruefungsmaterial.
    """
    data, container = read_exz(SOURCE_EXZ)
    _, questions = find_questions(data)

    kinds = {q.get("exm_question_types_id") for q in questions}
    if not {2, 13} <= kinds:
        raise SystemExit(
            f"{SOURCE_EXZ}: erwartet Fragetypen 13 (Multiple Choice) und "
            f"2 (offene Frage), gefunden {sorted(kinds)}. "
            f"Bitte zuerst 'python tools_template.py' ausfuehren."
        )
    if any(q.get("images") for q in questions):
        raise SystemExit(f"{SOURCE_EXZ}: enthaelt Bilder - nicht weitergeben.")

    write_exz(dest, data, container)


BEISPIEL = [
    (1, "Welche Aussagen zu HTTP treffen zu?", "multiple",
     [("HTTP ist zustandslos.", True),
      ("HTTP nutzt standardmaessig Port 443.", False),
      ("HTTP kennt die Methode GET.", True),
      ("HTTP verschluesselt Daten grundsaetzlich.", False)]),
    (2, "Welches Geraet arbeitet auf Schicht 3 des OSI-Modells?", "multiple",
     [("Router", True), ("Hub", False), ("Repeater", False), ("Steckdose", False)]),
    (3, "Erklaeren Sie den Unterschied zwischen TCP und UDP. "
        "(Zwei bis vier Saetze)", "freeanswer", []),
    (4, "Beschreiben Sie, wozu ein DNS-Server dient. "
        "(Zwei bis vier Saetze)", "freeanswer", []),
]


def build_example_workbook(dest: str) -> None:
    """Kleine Mappe mit beiden Fragetypen - zum Abschauen des Aufbaus."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fragen"
    header = ["Nr", "Frage", "Typ"]
    for i in range(1, 5):
        header += [f"Antwort {i}", "true / false"]
    ws.append(header)
    for nr, text, typ, options in BEISPIEL:
        row = [nr, text, typ]
        for answer, correct in options:
            row += [answer, "true" if correct else "false"]
        ws.append(row)
    widths = {"A": 5, "B": 58, "C": 12}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for col in "DFHJ":
        ws.column_dimensions[col].width = 34
    for col in "EGIK":
        ws.column_dimensions[col].width = 12
    ws.freeze_panes = "A2"
    wb.save(dest)


def build_blank_workbook(dest: str) -> int:
    """Leere Fragen-Vorlage uebernehmen und pruefen, dass sie leer IST."""
    shutil.copy(SOURCE_XLSX, dest)
    ws = openpyxl.load_workbook(dest).worksheets[0]
    filled = [
        r[0].row for r in ws.iter_rows(min_row=2)
        if any(c.value for i, c in enumerate(r) if i >= 1)
    ]
    if filled:
        raise SystemExit(
            f"{SOURCE_XLSX}: enthaelt Fragen in Zeile "
            f"{', '.join(map(str, filled[:5]))} - nicht weitergeben."
        )
    return ws.max_row


START_TXT_FILE = "paket/START-HIER.txt"


def read_start_text() -> str:
    """Anleitung fuer die Weitergabe - liegt als echte Textdatei vor."""
    with open(START_TXT_FILE, encoding="utf-8") as f:
        return f.read()


def build_bat(source: str) -> str:
    """Die BAT wandert unveraendert ins Paket.

    Repo und Paket haben denselben Aufbau (vorlage/ neben der BAT), deshalb
    stimmt der Vorlagenpfad in beiden. Geprueft wird das trotzdem.
    """
    text = open(source, encoding="ascii").read()
    if r"set \"TEMPLATE=vorlage\struktur-vorlage.exz\"".replace("\\\"", '"') \
            not in text:
        raise SystemExit(
            "tools_package: Excel-zu-EXZ.bat zeigt nicht auf "
            r"vorlage\struktur-vorlage.exz - build_bat() pruefen.")
    return text


def main(argv):
    out_zip = argv[0] if argv else f"output/{PKG}.zip"
    staging = os.path.join("output", "_paket", PKG)
    if os.path.isdir(os.path.dirname(staging)):
        shutil.rmtree(os.path.dirname(staging))
    os.makedirs(os.path.join(staging, "vorlage"), exist_ok=True)
    os.makedirs(os.path.join(staging, "exz"), exist_ok=True)


    build_structure_template(os.path.join(staging, "vorlage",
                                          "struktur-vorlage.exz"))
    removed = build_blank_workbook(os.path.join(staging, "vorlage",
                                                "Fragen-Vorlage.xlsx"))
    build_example_workbook(os.path.join(staging, "vorlage",
                                        "Beispiel-Fragen.xlsx"))
    print(f"Excel-Vorlage geleert: {removed} Fragezeilen entfernt")

    with open(os.path.join(staging, "Excel-zu-EXZ.bat"), "w",
              encoding="ascii", newline="\r\n") as f:
        f.write(build_bat("Excel-zu-EXZ.bat"))
    with open(os.path.join(staging, "START-HIER.txt"), "w",
              encoding="utf-8", newline="\r\n") as f:
        f.write(read_start_text())

    # Alle Module mitnehmen - eine feste Liste vergisst neue Dateien.
    modules = sorted(p for p in os.listdir("exz") if p.endswith(".py"))
    if "__init__.py" not in modules or "api.py" not in modules:
        raise SystemExit(f"exz/ sieht unvollstaendig aus: {modules}")
    for name in modules:
        shutil.copy(os.path.join("exz", name),
                    os.path.join(staging, "exz", name))
    shutil.copy("requirements.txt", staging)

    os.makedirs(os.path.dirname(out_zip) or ".", exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(staging):
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, os.path.dirname(staging))
                zf.write(full, rel.replace(os.sep, "/"))

    print(f"\ngeschrieben: {out_zip}  ({os.path.getsize(out_zip):,} Bytes)")
    with zipfile.ZipFile(out_zip) as zf:
        for info in zf.infolist():
            print(f"  {info.filename:<48} {info.file_size:>8,} Bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Baut eine schlanke Struktur-Vorlage mit je einer Frage pro unterstuetztem Typ.

    python tools_template.py [ziel.exz]

Dieses Skript ist nur fuer die Wartung gedacht und braucht echte
eduExaminer-Exporte als Quelle - die liegen bewusst NICHT im Repository.
Die fertige, inhaltsfreie Vorlage ist als vorlage/struktur-vorlage.exz
bereits enthalten; neu bauen muss man sie nur, wenn eduExaminer sein
Format aendert.

Quellen sind echte Exporte; uebernommen wird nur die Feldstruktur:
Fragetexte werden durch Platzhalter ersetzt, Punkte auf 0 gesetzt, Bilder,
Tags, Kommentare und Feedback entfernt. So enthaelt die Vorlage kein
Pruefungsmaterial und kann weitergegeben werden.
"""
from __future__ import annotations

import base64
import copy
import os
import re
import sys

from exz.exzfile import find_questions, read_exz, write_exz

# Quelle -> welche exm_question_types_id daraus uebernommen wird
SOURCES = [
    ("input/export.exz", 13, "Platzhalter Multiple Choice"),
    ("input/demo-alle-typen.exz", 2, "Platzhalter offene Frage"),
]

PLACEHOLDER_MC = (
    '<?xml version="1.0"?>\n<presentation>'
    '<version downcompatible="1">1</version>'
    '<material label="question"><mattext texttype="text/html">'
    "<![CDATA[Platzhalter]]></mattext></material>"
    '<response_lid ident="1"><render_choice shuffle="No">'
    + "".join(
        f'<response_label ident="{letter}"><material>'
        f'<mattext texttype="text/html"><![CDATA[{letter}]]></mattext>'
        "</material></response_label>"
        for letter in "ABCD"
    )
    + "</render_choice></response_lid>\n</presentation>\n"
)

PLACEHOLDER_ESSAY = (
    '<?xml version="1.0"?>\n<presentation>'
    '<version downcompatible="1">1</version>'
    '<material><mattext texttype="text/html">'
    "<![CDATA[Platzhalter]]></mattext></material>"
    "<settings><showquestiontextinsplitview>false"
    "</showquestiontextinsplitview></settings>"
    "<activateTinyMCE>true</activateTinyMCE>\n</presentation>\n"
)

b64 = lambda text: base64.b64encode(text.encode("utf-8")).decode("ascii")
unb64 = lambda value: base64.b64decode(value).decode("utf-8")


def sanitise(item, type_id, title):
    item = copy.deepcopy(item)
    item["title"] = title
    item["images"] = {} if isinstance(item.get("images"), dict) else []
    for key in ("tags", "comments", "question_instructions"):
        if isinstance(item.get(key), list):
            item[key] = []
    if isinstance(item.get("itemfeedback"), str):
        item["itemfeedback"] = ""

    rev = item["revisions"][0]
    item["revisions"] = [rev]
    rev["presentation"] = b64(
        PLACEHOLDER_ESSAY if type_id == 2 else PLACEHOLDER_MC)
    xml = unb64(rev["resprocessing"])
    xml = re.sub(r'(<setvar action="Set">)(-?[\d.]+)(</setvar>)',
                 r"\g<1>0\g<3>", xml)
    rev["resprocessing"] = b64(xml)
    if rev.get("feedback"):
        rev["feedback"] = b64("<feedbacks></feedbacks>")
    return item


def main(argv):
    dest = argv[0] if argv else "vorlage/struktur-vorlage.exz"

    base_data, container = read_exz(SOURCES[0][0])
    _, base_list = find_questions(base_data)

    collected = []
    for path, type_id, title in SOURCES:
        if not os.path.exists(path):
            raise SystemExit(f"Quelle fehlt: {path}")
        data, _ = read_exz(path)
        _, qlist = find_questions(data)
        match = next((q for q in qlist
                      if q.get("exm_question_types_id") == type_id), None)
        if match is None:
            raise SystemExit(f"{path}: keine Frage mit Typ-ID {type_id}")
        collected.append(sanitise(match, type_id, title))

    for offset, item in enumerate(collected):
        if isinstance(item.get("id"), int):
            item["id"] = 1 + offset

    base_list[:] = collected
    if isinstance(base_data.get("topics"), dict):
        base_data["topics"]["name"] = "Vorlage"
        base_data["topics"]["topics"] = []

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    write_exz(dest, base_data, container)

    check, _ = read_exz(dest)
    _, checked = find_questions(check)
    print(f"geschrieben: {dest}  ({os.path.getsize(dest):,} Bytes)")
    for q in checked:
        print(f"  Typ-ID {q['exm_question_types_id']:>2}  {q['title']:<28} "
              f"Bilder: {len(q.get('images') or {})}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

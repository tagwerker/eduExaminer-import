"""Liest Fragen-Arbeitsmappen ein - layout-, sprach- und typtolerant.

Zwei Layouts kommen in der Praxis vor und werden automatisch erkannt:

  TCExam-Vorlage : A=Nr  B=Frage  C=Typ  D/E F/G H/I ... (Antwort, true/false)
  Kurzform       : A=Frage  B=Typ                       (offene Fragen)

Die Erkennung sucht die Spalte, in der Typangaben wie "multiple" oder
"freeanswer" stehen; daraus ergibt sich alles Weitere. Eine Kopfzeile darf
vorhanden sein oder fehlen.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import openpyxl

MAX_ANSWERS = 6
SCAN_ROWS = 40

# Eingabewort -> interner Typ
TYPE_ALIASES = {
    "multiple": "multiple",
    "multiplechoice": "multiple",
    "multiple choice": "multiple",
    "multipleresponse": "multiple",
    "mc": "multiple",
    "mehrfachauswahl": "multiple",
    "freeanswer": "essay",
    "free answer": "essay",
    "freetext": "essay",
    "free text": "essay",
    "essay": "essay",
    "offen": "essay",
    "offene frage": "essay",
    "open": "essay",
    "text": "essay",
}

TRUE_WORDS = {
    "true", "wahr", "w", "1", "x", "ja", "j", "yes", "y",
    "richtig", "r", "correct", "vrai", "si", "t",
}
FALSE_WORDS = {
    "false", "falsch", "f", "0", "", "nein", "n", "no",
    "incorrect", "faux", "-",
}


class AnswerFlagError(ValueError):
    pass


class LayoutError(ValueError):
    pass


def parse_flag(value, where: str) -> bool:
    """WAHR/FALSCH, true/false, 1/0, x, ja/nein, echte Booleans - alles ok."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = str(value).strip().replace(" ", " ").strip().casefold()
    if token in TRUE_WORDS:
        return True
    if token in FALSE_WORDS:
        return False
    raise AnswerFlagError(
        f"{where}: '{value}' ist weder wahr noch falsch. "
        f"Erlaubt sind z.B. true/false, WAHR/FALSCH, 1/0, x, ja/nein."
    )


def clean_text(value) -> str:
    """NBSP & Co. raus, Zeilenumbrueche normalisieren, Unicode-NFC."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    for space in (" ", " ", " "):
        text = text.replace(space, " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalise_type(value) -> str | None:
    token = clean_text(value).casefold()
    return TYPE_ALIASES.get(token.replace("-", "").replace("_", "")) \
        or TYPE_ALIASES.get(token)


@dataclass
class QuestionImage:
    """Ein in der Arbeitsmappe eingebettetes Bild, einer Frage zugeordnet."""
    data: bytes
    ext: str
    width: int
    height: int
    row: int
    name: str = ""          # Dateiname im EXZ, vergibt exz/api.py

    @property
    def mime(self) -> str:
        return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "bmp": "image/bmp",
                "webp": "image/webp"}.get(self.ext.lower(), "application/octet-stream")


@dataclass
class Option:
    text: str
    correct: bool


@dataclass
class Question:
    number: int
    text: str
    qtype: str                       # "multiple" | "essay"
    options: list[Option] = field(default_factory=list)
    row: int = 0
    images: list[QuestionImage] = field(default_factory=list)

    @property
    def n_options(self) -> int:
        return len(self.options)

    @property
    def n_correct(self) -> int:
        return sum(1 for o in self.options if o.correct)


MAX_IMAGE_WIDTH = 700


def read_images(ws) -> dict[int, list[QuestionImage]]:
    """Eingebettete Bilder, nach der Zeile ihres Ankers gruppiert (1-basiert).

    openpyxl liefert die Bilder ueber ws._images; der Anker sagt, an welcher
    Zelle das Bild haengt. Breite Bilder werden proportional verkleinert,
    damit sie die Pruefungsansicht nicht sprengen.
    """
    out: dict[int, list[QuestionImage]] = {}
    for image in getattr(ws, "_images", []) or []:
        anchor = getattr(image, "anchor", None)
        start = getattr(anchor, "_from", None)
        if start is None:
            continue
        try:
            data = image._data()
        except Exception:                                   # noqa: BLE001
            continue
        if not data:
            continue

        width = int(getattr(image, "width", 0) or 0)
        height = int(getattr(image, "height", 0) or 0)
        if width > MAX_IMAGE_WIDTH and height:
            height = max(1, round(height * MAX_IMAGE_WIDTH / width))
            width = MAX_IMAGE_WIDTH

        row = start.row + 1
        out.setdefault(row, []).append(QuestionImage(
            data=data,
            ext=(getattr(image, "format", "") or "png").lower(),
            width=width, height=height, row=row,
        ))
    return out


@dataclass
class Layout:
    col_type: int          # 0-basiert
    col_text: int
    col_number: int | None
    first_answer: int
    first_row: int

    def describe(self) -> str:
        col = lambda i: chr(ord("A") + i)
        parts = []
        if self.col_number is not None:
            parts.append(f"{col(self.col_number)}=Nr")
        parts += [f"{col(self.col_text)}=Frage", f"{col(self.col_type)}=Typ"]
        parts.append(f"Antworten ab {col(self.first_answer)}")
        return ", ".join(parts) + f", Daten ab Zeile {self.first_row}"


def detect_layout(ws) -> Layout:
    """Findet die Typspalte anhand ihres Inhalts und leitet den Rest ab."""
    hits: dict[int, int] = {}
    first_hit_row: dict[int, int] = {}
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, SCAN_ROWS)):
        for i, cell in enumerate(row):
            if normalise_type(cell.value):
                hits[i] = hits.get(i, 0) + 1
                first_hit_row.setdefault(i, cell.row)

    if not hits:
        raise LayoutError(
            "Keine Typspalte gefunden. Es muss eine Spalte geben, in der pro "
            "Zeile 'multiple' oder 'freeanswer' bzw. 'essay' steht."
        )

    col_type = max(hits, key=lambda i: (hits[i], -i))
    if col_type == 0:
        raise LayoutError(
            f"Die Typangaben stehen in Spalte A. Der Fragetext muss links "
            f"davon stehen - bitte eine Spalte einfuegen."
        )

    col_text = col_type - 1
    col_number = col_text - 1 if col_text >= 1 else None
    first_row = first_hit_row[col_type]
    last_scan = min(ws.max_row, SCAN_ROWS)

    if col_number is not None:
        numeric = sum(
            1 for r in range(first_row, last_scan + 1)
            if isinstance(ws.cell(r, col_number + 1).value, (int, float))
        )
        if numeric == 0:
            col_number = None

    # Manche Vorlagen fuellen die Kopfzeile als Beispiel aus ("antwort1 / true"),
    # inklusive des Worts "multiple" in der Typspalte. Strukturell ist sie dann
    # nicht von einer echten Frage zu unterscheiden - erkennbar ist sie nur
    # daran, dass in der Nummernspalte eine Beschriftung statt einer Zahl steht,
    # waehrend die folgenden Zeilen durchnummeriert sind.
    if col_number is not None and first_row < last_scan:
        head = ws.cell(first_row, col_number + 1).value
        below = [ws.cell(r, col_number + 1).value
                 for r in range(first_row + 1, last_scan + 1)]
        numbered = sum(1 for v in below if isinstance(v, (int, float)))
        if (head is not None and not isinstance(head, (int, float))
                and numbered >= 2):
            first_row += 1

    return Layout(col_type, col_text, col_number, col_type + 1, first_row)


def read_questions(path: str, sheet: str | None = None
                   ) -> tuple[list[Question], list[str], Layout]:
    """Gibt (Fragen, Warnungen, erkanntes Layout) zurueck."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    layout = detect_layout(ws)

    # Bilder liest nur die nicht-schreibgeschuetzte Mappe; data_only verliert
    # sie nicht, aber der Anker steht am Zellbezug, nicht am Wert.
    images_by_row = read_images(
        openpyxl.load_workbook(path)[ws.title]
    )

    questions: list[Question] = []
    warnings: list[str] = []

    for row in ws.iter_rows(min_row=layout.first_row, max_row=ws.max_row):
        values = [c.value for c in row]
        rownum = row[0].row
        get = lambda i: values[i] if 0 <= i < len(values) else None

        text = clean_text(get(layout.col_text))
        raw_type = get(layout.col_type)
        images = images_by_row.get(rownum, [])
        if not text and not raw_type and not images:
            continue
        if not text and not images:
            warnings.append(f"Zeile {rownum}: Typ angegeben, aber kein Fragetext "
                            f"- uebersprungen.")
            continue

        qtype = normalise_type(raw_type)
        if qtype is None:
            if clean_text(raw_type):
                warnings.append(
                    f"Zeile {rownum}: unbekannter Fragetyp "
                    f"'{clean_text(raw_type)}' - als 'multiple' behandelt.")
            qtype = "multiple"

        options: list[Option] = []
        if qtype == "multiple":
            for i in range(MAX_ANSWERS):
                a_col = layout.first_answer + i * 2
                answer = clean_text(get(a_col))
                if not answer:
                    continue
                options.append(Option(answer, parse_flag(
                    get(a_col + 1),
                    f"Zeile {rownum}, Spalte {chr(ord('A') + a_col + 1)}")))

            if not options:
                warnings.append(
                    f"Zeile {rownum}: 'multiple' ohne Antworten - uebersprungen.")
                continue
            n_ok = sum(1 for o in options if o.correct)
            if n_ok == 0:
                warnings.append(f"Zeile {rownum}: keine richtige Antwort markiert.")
            elif n_ok == len(options):
                warnings.append(f"Zeile {rownum}: ALLE Antworten sind richtig markiert.")

        number = len(questions) + 1
        if layout.col_number is not None:
            try:
                number = int(get(layout.col_number))
            except (TypeError, ValueError):
                pass

        questions.append(
            Question(number, text, qtype, options, rownum, images))

    verwendet = {im.row for q in questions for im in q.images}
    for row in sorted(set(images_by_row) - verwendet):
        warnings.append(
            f"Zeile {row}: Bild gefunden, aber keine Frage in dieser Zeile "
            f"- das Bild wird nicht uebernommen.")

    return questions, warnings, layout

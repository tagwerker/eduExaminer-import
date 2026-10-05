"""Wiederverwendbarer Kern: Excel -> EXZ, ohne Dateisystem und ohne print.

Hier liegt die Logik, die sowohl die Kommandozeile (``python -m exz build``)
als auch die Streamlit-App benutzen. Alles arbeitet mit Bytes und Objekten,
damit ein Upload nicht erst auf die Platte geschrieben werden muss.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from .excel import Layout, Question, read_questions
from .exzfile import b64_decode_text, b64_encode_text, dumps_exz, find_questions, loads_exz
from .qti import build_evaluation, build_presentation
from .scoring import (
    DEFAULT_DECIMALS,
    DEFAULT_ESSAY_POINTS,
    DEFAULT_TOTAL,
    POINTS_PER_OPTION,
    Points,
    compute,
    compute_essay,
)

SCORE_HINTS = (
    "setvar", "resprocessing", "score", "points", "punkt",
    "evaluation", "grading", "bewertung", "decvar",
)
ID_KEYS = re.compile(r"(^|_)(id|uuid|guid)$", re.I)
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
NS = uuid.UUID("6f1c0a1e-0000-4000-8000-000000000001")

# exm_question_types_id aus echten Exporten:
#   13 = Multiple Response (mehrere richtige Antworten moeglich)
#    2 = Discursive Writing (offene Frage, Korrektur von Hand)
PREFERRED_TYPE_IDS = {"multiple": 13, "essay": 2}

TYPE_LABELS = {"multiple": "Multiple Choice", "essay": "offene Fragen"}


class BuildError(Exception):
    """Fehler, dessen Text direkt der Person gezeigt werden kann."""


# ------------------------------------------------------------- Hilfsmittel --

def xml_fields(node: dict) -> dict[str, tuple[str, str]]:
    """{feldname: (root-tag, xml)} fuer alle base64-XML-Felder eines dicts."""
    found = {}
    for key, value in node.items():
        text = b64_decode_text(value)
        if not text:
            continue
        stripped = text.lstrip()
        if not stripped.startswith("<"):
            continue
        body = stripped.split("?>", 1)[-1]
        m = re.search(r"<([A-Za-z_][\w.:-]*)[\s>/]", body)
        found[key] = (m.group(1) if m else "?", text)
    return found


def classify_prototype(question: dict, pres_field: str) -> str | None:
    """Fragetyp einer Vorlagen-Frage aus ihrem presentation-XML ableiten.

    Offene Fragen haben GAR KEIN Antwort-Element - deshalb wird auf das
    Fehlen von response_/render_ geprueft, nicht auf ein bestimmtes Tag.
    Hotspot & Co. (response_xy, render_hotspot) fallen bewusst durch.
    """
    revs = question.get("revisions") or []
    if not revs:
        return None
    xml = b64_decode_text(revs[0].get(pres_field)) or ""
    if "<response_lid" in xml and "<render_choice" in xml:
        return "multiple"
    if "<response_" not in xml and "<render_" not in xml:
        return "essay"
    return None


def collect_prototypes(qlist: list, pres_field: str) -> dict[str, dict]:
    """{typ: Prototyp-Frage} aus der Vorlage.

    Bevorzugt werden die aus echten Exporten bekannten Typ-IDs; nur wenn
    die fehlen, entscheidet die Struktur. Das verhindert, dass bei einer
    Vorlage mit vielen Fragetypen versehentlich "Multiple Choice" (eine
    Antwort) statt "Multiple Response" (mehrere Antworten) erwischt wird.
    """
    protos: dict[str, dict] = {}
    for kind, type_id in PREFERRED_TYPE_IDS.items():
        for question in qlist:
            if question.get("exm_question_types_id") == type_id:
                protos[kind] = question
                break
    for question in qlist:
        kind = classify_prototype(question, pres_field)
        if kind and kind not in protos:
            protos[kind] = question
    return protos


def strip_inherited(item: dict) -> None:
    """Was der Prototyp mitbringt, aber nicht vererbt werden darf."""
    if isinstance(item.get("images"), dict):
        item["images"] = {}
    elif isinstance(item.get("images"), list):
        item["images"] = []
    for key in ("tags", "comments", "question_instructions"):
        if isinstance(item.get(key), list):
            item[key] = []
    if isinstance(item.get("itemfeedback"), str):
        item["itemfeedback"] = ""


def refresh_ids(node: Any, seed: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and ID_KEYS.search(key):
                node[key] = (str(uuid.uuid5(NS, f"{seed}|{value}"))
                             if UUID_RE.match(value) else value)
            else:
                refresh_ids(value, seed)
    elif isinstance(node, list):
        for value in node:
            refresh_ids(value, seed)


def assign_ids(items: list[dict]) -> None:
    """Fortlaufende, eindeutige Ganzzahl-IDs - der Prototyp liefert nur eine."""
    base = 1
    for item in items:
        if isinstance(item.get("id"), int):
            base = item["id"]
            break
    for offset, item in enumerate(items):
        if isinstance(item.get("id"), int):
            item["id"] = base + offset


def name_images(questions: list[Question]) -> int:
    """Jedem Bild einen innerhalb des Exports eindeutigen Dateinamen geben."""
    counter = 0
    for q in questions:
        for image in getattr(q, "images", []) or []:
            counter += 1
            image.name = f"{counter}.{image.ext}"
    return counter


def attach_images(item: dict, question: Question) -> None:
    """Bilder einer Frage in das images-Dict des Frage-Objekts eintragen.

    Muss NACH der ID-Vergabe laufen: Schluessel und dataID enthalten die
    endgueltige Frage-ID. Im HTML steht dagegen der Platzhalter
    ##question_id##, den eduExaminer selbst ersetzt.
    """
    images = getattr(question, "images", None)
    if not images:
        return
    qid = item.get("id")
    store = item.setdefault("images", {})
    if not isinstance(store, dict):
        store = item["images"] = {}
    for image in images:
        if not image.name:
            continue
        key = f"questionresources/{qid}/{image.name}"
        store[key] = {
            "dataType": "exmimg",
            "filename_original": f"zeile-{image.row}.{image.ext}",
            "filename_new": image.name,
            "type": "question",
            "dataID": qid,
            "resourcesCode": hashlib.sha1(image.data).hexdigest()[:10],
            "mimeType": image.mime,
            "path": f"questionresources/##question_id##/{image.name}",
            "data": base64.b64encode(image.data).decode("ascii"),
            "use_as_question_enclosure": 0,
            "print_with_testletter": 0,
            "download_in_question": 0,
        }


def set_title(node: dict, question: Question,
              template: str = "Frage {nr:02d}") -> None:
    """Titel setzen. '{nr}' = Fragennummer, '{text}' = Fragetext."""
    value = template.format(nr=question.number, text=question.text)[:120]
    for key in ("title", "name", "label", "questionTitle"):
        if isinstance(node.get(key), str):
            node[key] = value
            return


# ----------------------------------------------------------------- Optionen --

@dataclass
class BuildOptions:
    total: float | None = None      # None = ein Punkt je Antwortmoeglichkeit
    essay_points: float = DEFAULT_ESSAY_POINTS
    decimals: int = DEFAULT_DECIMALS
    scheme: str = "balanced"
    plus: float | None = None
    minus: float | None = None
    negative: bool = False
    shuffle: bool = False
    title_format: str = "Frage {nr:02d}"
    presentation_field: str = "presentation"
    score_field: str | None = None


@dataclass
class BuildResult:
    exz: bytes
    questions: list[Question]
    points: list[Points]
    warnings: list[str] = field(default_factory=list)
    layout: Layout | None = None
    prototypes: dict[str, Any] = field(default_factory=dict)
    score_field: str = ""
    container: str = ""
    n_images: int = 0

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for q in self.questions:
            out[q.qtype] = out.get(q.qtype, 0) + 1
        return out

    def summary(self) -> str:
        return ", ".join(f"{n}x {TYPE_LABELS.get(t, t)}"
                         for t, n in sorted(self.counts.items()))


def question_total(question: Question, opts: BuildOptions) -> float:
    """Maximalpunkte einer Multiple-Choice-Frage.

    Ohne ausdrueckliche Vorgabe gilt ein Punkt je Antwortmoeglichkeit:
    4 Antworten -> 4 Punkte, 6 Antworten -> 6 Punkte.
    """
    if opts.total is not None:
        return opts.total
    return max(1, question.n_options) * POINTS_PER_OPTION


def points_for(question: Question, opts: BuildOptions) -> Points:
    """Punkte je Frage - offene Fragen bekommen eine feste Punktzahl."""
    if question.qtype != "multiple":
        return compute_essay(opts.essay_points, opts.decimals)
    return compute(question.n_options, question.n_correct,
                   question_total(question, opts),
                   opts.decimals, scheme=opts.scheme,
                   plus=opts.plus, minus=opts.minus)


# -------------------------------------------------------------------- Bauen --

def read_workbook(source: str | BinaryIO, sheet: str | None = None):
    """Excel einlesen - Pfad oder dateiaehnliches Objekt (z.B. ein Upload)."""
    return read_questions(source, sheet)


def build_exz(
    questions: list[Question],
    template: bytes | str,
    opts: BuildOptions | None = None,
) -> BuildResult:
    """Erzeugt die fertige EXZ-Datei als Bytes.

    ``template`` ist eine echte eduExaminer-Exportdatei (Pfad oder Bytes);
    aus ihr stammt die Feldstruktur je Fragetyp.
    """
    opts = opts or BuildOptions()
    if not questions:
        raise BuildError("Die Datei enthaelt keine auswertbaren Fragen.")

    if isinstance(template, (str, bytes)) and not isinstance(template, bytes):
        with open(template, "rb") as f:
            template = f.read()
    data, container = loads_exz(template)

    _, qlist = find_questions(data)
    if qlist is None:
        raise BuildError("In der Strukturvorlage wurde keine Fragenliste gefunden.")

    pres_field = opts.presentation_field
    proto_rev = qlist[0]["revisions"][0]
    if pres_field not in proto_rev:
        raise BuildError(
            f"Das Feld '{pres_field}' fehlt in der Strukturvorlage. "
            f"Vorhanden sind: {', '.join(proto_rev)}."
        )

    prototypes = collect_prototypes(qlist, pres_field)
    needed = {q.qtype for q in questions}
    missing = sorted(needed - set(prototypes))
    if missing:
        names = {"essay": "offene Frage (Essay)",
                 "multiple": "Multiple Choice / Multiple Response"}
        raise BuildError(
            "Die Strukturvorlage enthaelt keine Frage vom Typ "
            + ", ".join(names.get(m, m) for m in missing)
            + ". Die interne Typ-ID laesst sich nicht erraten - sie muss aus "
              "einem echten Export stammen. Bitte in eduExaminer eine Frage "
              "dieses Typs anlegen, exportieren und die Datei als Vorlage "
              "hinterlegen."
        )

    score_field = opts.score_field
    if not score_field:
        candidates = [
            key for key, (_tag, xml) in xml_fields(proto_rev).items()
            if key != pres_field
            and any(h in xml.lower() or h in key.lower() for h in SCORE_HINTS)
        ]
        if len(candidates) != 1:
            raise BuildError(
                "Das Bewertungsfeld in der Strukturvorlage ist nicht eindeutig "
                f"(Kandidaten: {', '.join(candidates) or 'keine'})."
            )
        score_field = candidates[0]

    name_images(questions)

    all_points: list[Points] = []
    new_questions: list[dict] = []
    for q in questions:
        pts = points_for(q, opts)
        all_points.append(pts)
        item = copy.deepcopy(prototypes[q.qtype])
        strip_inherited(item)
        refresh_ids(item, f"q{q.number}")
        rev = item["revisions"][0]
        item["revisions"] = [rev]
        rev[pres_field] = b64_encode_text(
            build_presentation(q, shuffle=opts.shuffle))
        rev[score_field] = b64_encode_text(
            build_evaluation(q, pts, allow_negative=opts.negative))
        set_title(rev, q, opts.title_format)
        set_title(item, q, opts.title_format)
        new_questions.append(item)

    assign_ids(new_questions)
    for item, q in zip(new_questions, questions):
        attach_images(item, q)
    qlist[:] = new_questions

    return BuildResult(
        exz=dumps_exz(data, container),
        questions=questions,
        points=all_points,
        prototypes={k: v.get("exm_question_types_id") for k, v in prototypes.items()},
        score_field=score_field,
        container=container.kind,
        n_images=sum(len(getattr(q, "images", []) or []) for q in questions),
    )


def convert(
    source: str | BinaryIO,
    template: bytes | str,
    opts: BuildOptions | None = None,
    sheet: str | None = None,
) -> BuildResult:
    """Ein Aufruf von der Excel-Datei bis zu den fertigen EXZ-Bytes."""
    questions, warnings, layout = read_workbook(source, sheet)
    result = build_exz(questions, template, opts)
    result.warnings = warnings
    result.layout = layout
    return result

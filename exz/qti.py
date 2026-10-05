"""XML-Fragmente fuer das EXZ - exakt im Dialekt von eduExaminer/bizExaminer.

Verifiziert gegen einen echten Export (46 Fragen, Topic "Datenbanken II - Big Data").
Beide Felder liegen base64-kodiert in
    topics.questions[i].revisions[0].presentation
    topics.questions[i].revisions[0].resprocessing

Eigenheiten, die eingehalten werden muessen:
  * Zeilenumbruch nach der XML-Deklaration, sonst alles auf einer Zeile
  * presentation: Umbruch vor </presentation>, abschliessender Umbruch
  * mattext-CDATA enthaelt KLARTEXT, kein <p>...</p>
  * resprocessing nutzt action="Set" (nicht "Add") und ZWEI respconditions
    pro Antwort: angekreuzt -> Punkte, nicht angekreuzt -> 0
  * <global> mit mrAnswersType / evaluationType / allowNegativeOutcome
  * kein <settings>-Block, kein rcardinality

Offene Fragen (eduExaminer-Typ 2, "Discursive Writing") sind gegen einen
Demo-Export mit allen Fragetypen geprueft und sehen anders aus als vermutet:
  * KEIN <response_str> / <render_fib> - offene Fragen haben gar kein
    Antwort-Element
  * <material> OHNE label="question"
  * <activateTinyMCE>true</activateTinyMCE> schaltet den Formatiereditor frei
  * <global> enthaelt NUR allowNegativeOutcome
  * genau eine <respcondition title="Scored"> mit <other/> als Bedingung
"""
from __future__ import annotations

import string

from .excel import Question
from .scoring import Points, fmt

LETTERS = string.ascii_uppercase

# Aus dem echten Export. mrAnswersType=1 -> Mehrfachauswahl erlaubt,
# evaluationType=1 -> "Award points per answer",
# allowNegativeOutcome -> Oberflaeche "Negative points possible" (0=No, 1=Yes).
# Mit 0 wird die Punktzahl je Frage bei 0 abgeschnitten; dann liegt der
# Erwartungswert beim Raten leicht ueber 0 statt genau darauf.
def global_block(allow_negative: bool = False) -> str:
    return (
        "<global>"
        "<mrAnswersType>1</mrAnswersType>"
        "<evaluationType>1</evaluationType>"
        f"<allowNegativeOutcome>{1 if allow_negative else 0}</allowNegativeOutcome>"
        "</global>"
    )


def cdata(text: str) -> str:
    """CDATA-Block; ']]>' im Text wuerde ihn sonst vorzeitig schliessen."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def as_html(text: str) -> str:
    """Der echte Export legt Klartext ab - Absaetze nur bei echtem Umbruch."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    return "".join(f"<p>{line}</p>" for line in lines)


def image_tag(image) -> str:
    """<img> mit den Platzhaltern, die eduExaminer beim Anzeigen aufloest.

    ##images_path## und ##question_id## setzt das System selbst ein - der
    Pfad darf deshalb NICHT auf eine konkrete Frage-ID zeigen.
    """
    size = ""
    if image.width and image.height:
        size = f' width="{image.width}" height="{image.height}"'
    return (f'<img src="##images_path##questionresources/##question_id##/'
            f'{image.name}"{size} alt="" />')


def question_html(q: Question) -> str:
    """Fragetext plus eingebettete Bilder als HTML fuer das CDATA.

    Ohne Bilder bleibt die Ausgabe exakt wie bisher - nur so bleibt das
    erzeugte XML bitgenau identisch zu echten eduExaminer-Exporten.
    """
    body = as_html(q.text)
    if not getattr(q, "images", None):
        return body
    chunks = []
    if body:
        chunks.append(body if body.startswith("<p>") else f"<p>{body}</p>")
    chunks += [f"<p>{image_tag(im)}</p>" for im in q.images if im.name]
    return "".join(chunks)


def _mattext(text: str) -> str:
    return f'<mattext texttype="text/html">{cdata(as_html(text))}</mattext>'


def _mattext_html(html: str) -> str:
    """Wie _mattext, aber der Inhalt ist bereits fertiges HTML."""
    return f'<mattext texttype="text/html">{cdata(html)}</mattext>'


SPLITVIEW = ("<settings><showquestiontextinsplitview>false"
             "</showquestiontextinsplitview></settings>")


def build_presentation(q: Question, shuffle: bool = False,
                       rows: int = 10) -> str:
    if q.qtype != "multiple":
        # Offene Frage: nur der Text, KEIN Antwort-Element, Editor aktiv.
        return (
            '<?xml version="1.0"?>\n<presentation>'
            '<version downcompatible="1">1</version>'
            f"<material>{_mattext_html(question_html(q))}</material>"
            f"{SPLITVIEW}"
            "<activateTinyMCE>true</activateTinyMCE>"
            "\n</presentation>\n"
        )

    parts = [
        '<?xml version="1.0"?>\n<presentation>',
        '<version downcompatible="1">1</version>',
        f'<material label="question">{_mattext_html(question_html(q))}</material>',
    ]

    if q.qtype == "multiple":
        parts.append('<response_lid ident="1">')
        parts.append(f'<render_choice shuffle="{"Yes" if shuffle else "No"}">')
        for i, opt in enumerate(q.options):
            parts.append(
                f'<response_label ident="{LETTERS[i]}">'
                f"<material>{_mattext(opt.text)}</material>"
                "</response_label>"
            )
        parts.append("</render_choice></response_lid>")
    else:
        # Offene Frage: Eingabefeld statt Auswahlliste.
        parts.append(
            f'<response_str ident="1">'
            f'<render_fib rows="{rows}" columns="80"/>'
            "</response_str>"
        )

    return "".join(parts) + "\n</presentation>\n"


def build_evaluation(
    q: Question, pts: Points, allow_negative: bool = False
) -> str:
    """<resprocessing> mit den Punkten - der Grund fuer den ganzen Umweg."""
    if q.qtype != "multiple":
        # Offene Frage: eine einzige Bedingung mit der erreichbaren Punktzahl,
        # korrigiert wird von Hand. <global> nur mit allowNegativeOutcome.
        return (
            '<?xml version="1.0"?>\n<resprocessing>'
            "<outcomes><decvar/></outcomes>"
            "<global><allowNegativeOutcome>"
            f"{1 if allow_negative else 0}"
            "</allowNegativeOutcome></global>"
            '<respcondition title="Scored">'
            "<conditionvar><other/></conditionvar>"
            f'<setvar action="Set">{fmt(pts.correct)}</setvar>'
            '<displayfeedback linkrefid="Scored"/>'
            "</respcondition></resprocessing>\n"
        )

    parts = [
        '<?xml version="1.0"?>\n<resprocessing>',
        "<outcomes><decvar/></outcomes>",
        global_block(allow_negative),
    ]

    if q.qtype == "multiple":
        for i, opt in enumerate(q.options):
            letter = LETTERS[i]
            if opt.correct:
                ticked, unticked = pts.correct, pts.correct_unticked
            else:
                ticked, unticked = pts.wrong, pts.wrong_unticked
            # angekreuzt
            parts.append(
                f'<respcondition title="Answer{i + 1}">'
                f'<conditionvar><varequal respident="1">{letter}</varequal></conditionvar>'
                f'<setvar action="Set">{fmt(ticked)}</setvar>'
                f'<displayfeedback linkrefid="Antwort{i + 1}"/>'
                "</respcondition>"
            )
            # nicht angekreuzt
            parts.append(
                f'<respcondition title="Answer{i + 1}">'
                f"<conditionvar><not>"
                f'<varequal respident="1">{letter}</varequal>'
                f"</not></conditionvar>"
                f'<setvar action="Set">{fmt(unticked)}</setvar>'
                f'<displayfeedback linkrefid="Antwort{i + 1}"/>'
                "</respcondition>"
            )

    return "".join(parts) + "</resprocessing>\n"

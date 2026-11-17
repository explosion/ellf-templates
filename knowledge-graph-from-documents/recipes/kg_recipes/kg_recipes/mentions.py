"""Mentions: spans of an entity type in a passage.

They're labelled in the mentions task (``kg_mentions``) over the Documents asset. Rules and pretrained models
are labellers there too: their mentions are saved to the task's dataset under their own
annotator names, built the way the task builds its examples, so review and the scores
treat them like any other labeller.
"""

import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from .data import Answer


@dataclass(frozen=True)
class Mention:
    doc_id: str
    passage_id: str
    start: int
    end: int
    text: str
    type: str

    @property
    def key(self) -> Tuple[str, int, int, str]:
        return (self.passage_id, self.start, self.end, self.type)


def mentions_in(eg: dict, types: Optional[Iterable[str]] = None) -> List[Mention]:
    """The mentions in one accepted spans answer."""
    meta = eg.get("meta") or {}
    text = eg.get("text", "")
    wanted = set(types) if types is not None else None
    found = []
    for span in eg.get("spans") or []:
        label = span.get("label")
        if wanted is not None and label not in wanted:
            continue
        start, end = int(span["start"]), int(span["end"])
        found.append(
            Mention(
                doc_id=str(meta.get("doc_id", "")),
                passage_id=str(meta.get("passage_id", "")),
                start=start,
                end=end,
                text=text[start:end],
                type=label,
            )
        )
    return found


def mentions_from_answers(answers: Iterable[Answer], types: Optional[Iterable[str]] = None) -> List[Mention]:
    """Every distinct mention in the accepted answers, e.g. of a settled dataset."""
    seen: Dict[Tuple, Mention] = {}
    for eg, _ in answers:
        if eg.get("answer") != "accept":
            continue
        for m in mentions_in(eg, types):
            seen.setdefault(m.key, m)
    return sorted(seen.values(), key=lambda m: (m.doc_id, m.passage_id, m.start))


# Abbreviations defined in the text, after Schwartz and Hearst (2003): a short form in
# parentheses after its long form, whose characters it takes in order.
SHORT_FORM_RE = re.compile(r"\(([^()]{1,12})\)")


def _matches(long_form: str, short: str) -> Optional[str]:
    """The end of ``long_form`` that ``short`` abbreviates, or None."""
    s, l = len(short) - 1, len(long_form) - 1
    while s >= 0:
        c = short[s].lower()
        if not c.isalnum():
            s -= 1
            continue
        while l >= 0 and (long_form[l].lower() != c or (s == 0 and l > 0 and long_form[l - 1].isalnum())):
            l -= 1
        if l < 0:
            return None
        s -= 1
        l -= 1
    return long_form[l + 1 :].strip()


def abbreviations(text: str) -> Dict[str, str]:
    """Short form → long form, for every abbreviation the text defines."""
    found: Dict[str, str] = {}
    for m in SHORT_FORM_RE.finditer(text):
        short = m.group(1).strip()
        if not (2 <= len(short) <= 10) or not any(c.isalpha() for c in short) or " " in short.strip():
            continue
        if not short[0].isalnum():
            continue
        words = text[: m.start()].split()
        window = " ".join(words[-min(len(short) + 5, len(short) * 2) :])
        long_form = _matches(window, short)
        if long_form and len(long_form) > len(short) and short not in found:
            found[short] = long_form
    return found


def view_id(overlapping: bool) -> str:
    """The mentions task's view: compact unless mentions can overlap. Every answer saved to
    a mentions dataset uses it, since a review refuses datasets with different views."""
    return "spans_manual" if overlapping else "ner_manual"


def model_spans(nlp, texts: Iterable[str], label_map: Dict[str, str], types: Iterable[str]) -> Iterator[List[dict]]:
    """A pretrained pipeline's entities as spans, its labels mapped to entity types."""
    wanted = set(types)
    for doc in nlp.pipe(texts):
        spans = []
        for ent in doc.ents:
            label = label_map.get(ent.label_, ent.label_)
            if label in wanted:
                spans.append({"start": ent.start_char, "end": ent.end_char, "label": label})
        yield spans


def as_answer(task: dict, spans: List[dict], annotator: str) -> dict:
    """The task, already hashed like the mentions task's examples, answered with these spans."""
    return {
        **task,
        "spans": spans,
        "answer": "accept",
        "_annotator_id": annotator,
        "_session_id": annotator,
    }


def label_tasks(
    tasks: Iterable[dict], find: Callable[[List[str]], Iterable[List[dict]]], annotator: str, batch: int = 256
) -> Iterator[dict]:
    """Answer every task with what ``find`` returns for its text, in batches."""
    chunk: List[dict] = []

    def flush() -> Iterator[dict]:
        for task, spans in zip(chunk, find([t["text"] for t in chunk])):
            yield as_answer(task, spans, annotator)

    for task in tasks:
        chunk.append(task)
        if len(chunk) >= batch:
            yield from flush()
            chunk = []
    if chunk:
        yield from flush()


def token_aligned(nlp, text: str, spans: List[dict]) -> Tuple[List[dict], int, int]:
    """The spans widened to whole tokens, as the mentions task marks them.

    Returns the spans, how many were widened, and how many covered no token and were
    left out. Gold labels made outside spaCy often end inside a token.
    """
    doc = nlp.make_doc(text)
    out, widened, dropped = [], 0, 0
    for span in spans:
        aligned = doc.char_span(int(span["start"]), int(span["end"]), alignment_mode="expand")
        if aligned is None or not aligned.text.strip():
            dropped += 1
            continue
        if aligned.start_char != span["start"] or aligned.end_char != span["end"]:
            widened += 1
        out.append({**span, "start": aligned.start_char, "end": aligned.end_char})
    return out, widened, dropped

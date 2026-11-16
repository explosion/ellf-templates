"""The documents format every other step reads.

A source is turned into documents, one JSON object per document:

    {"doc_id": "D1", "version": "2", "date": "2024-05-01", "title": "...", "url": "...",
     "passages": [{"text": "...", "section": "Results", "kind": "paragraph"}, ...]}

or, without passages, with the whole text in "text", which is split into paragraphs at
blank lines. Only "doc_id" and the text are required.

The Documents asset then has one row per passage, in the shape tasks read:

    {"text": "...", "meta": {"doc_id": "D1", "passage_id": "D1:0", "doc_version": "2",
     "doc_date": "2024-05-01", "section": "Results", "kind": "paragraph", "title": "..."}}

A passage's kind is "paragraph", "table_row" or "document"; a "document" passage is the
whole document, for relations that are stated across a document rather than in one place.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

KINDS = ("paragraph", "table_row", "document")
BLANK_LINES_RE = re.compile(r"\n\s*\n")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")


@dataclass
class Passage:
    text: str
    section: str = ""
    kind: str = "paragraph"


@dataclass
class Document:
    doc_id: str
    passages: List[Passage]
    version: str = ""
    date: str = ""
    title: str = ""
    url: str = ""
    extra: Dict = field(default_factory=dict)


def clean(text: str) -> str:
    """Collapse runs of spaces and tabs, keep line breaks, strip the ends."""
    return "\n".join(SPACE_RE.sub(" ", line).strip() for line in text.split("\n")).strip()


def split_paragraphs(text: str) -> List[str]:
    """Paragraphs separated by blank lines, with line breaks inside them joined."""
    paragraphs = []
    for block in BLANK_LINES_RE.split(text):
        joined = " ".join(line.strip() for line in block.split("\n") if line.strip())
        if joined:
            paragraphs.append(joined)
    return paragraphs


def parse_document(row: dict, *, whole_document: bool = False) -> Document:
    """A document from one input row. Raises ValueError with the reason if the row can't be used.

    With ``whole_document``, the document also gets one passage holding all of its text.
    """
    doc_id = str(row.get("doc_id") or "").strip()
    if not doc_id:
        raise ValueError("a document needs a 'doc_id'")
    passages: List[Passage] = []
    if row.get("passages"):
        for i, p in enumerate(row["passages"]):
            if isinstance(p, str):
                p = {"text": p}
            text = clean(str(p.get("text") or ""))
            if not text:
                continue
            kind = p.get("kind") or "paragraph"
            if kind not in KINDS:
                raise ValueError(f"document {doc_id}, passage {i}: kind must be one of {', '.join(KINDS)}, not {kind!r}")
            passages.append(Passage(text=text, section=str(p.get("section") or ""), kind=kind))
    elif row.get("text"):
        passages = [Passage(text=t) for t in split_paragraphs(str(row["text"]))]
    else:
        raise ValueError(f"document {doc_id} has neither 'passages' nor 'text'")
    if not passages:
        raise ValueError(f"document {doc_id} has no text")
    if whole_document and not any(p.kind == "document" for p in passages):
        body = "\n\n".join(p.text for p in passages if p.kind != "document")
        passages.append(Passage(text=body, section="", kind="document"))
    known = {"doc_id", "version", "date", "title", "url", "passages", "text"}
    return Document(
        doc_id=doc_id,
        passages=passages,
        version=str(row.get("version") or ""),
        date=str(row.get("date") or ""),
        title=str(row.get("title") or ""),
        url=str(row.get("url") or ""),
        extra={k: v for k, v in row.items() if k not in known},
    )


def passage_rows(doc: Document) -> Iterator[dict]:
    """The document's passages as rows of the Documents asset."""
    for i, p in enumerate(doc.passages):
        meta = {
            "doc_id": doc.doc_id,
            "passage_id": f"{doc.doc_id}:{i}",
            "doc_version": doc.version,
            "doc_date": doc.date,
            "section": p.section,
            "kind": p.kind,
        }
        if doc.title:
            meta["title"] = doc.title
        if doc.url:
            meta["url"] = doc.url
        yield {"text": p.text, "meta": meta}


def in_eval(doc_id: str, share: float, seed: str = "eval") -> bool:
    """Whether a document belongs to the evaluation documents.

    Decided by a hash of its id, so the same document always lands on the same side and
    adding documents later never moves earlier ones.
    """
    digest = hashlib.sha256(f"{seed}:{doc_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12) < share


def split(docs: Iterable[Document], share: float, seed: str = "eval") -> Tuple[List[Document], List[Document]]:
    """The documents to label and the evaluation documents, split by document."""
    label, held = [], []
    for doc in docs:
        (held if in_eval(doc.doc_id, share, seed) else label).append(doc)
    return label, held


def doc_key(meta: dict) -> Tuple[str, str]:
    """A document's identity across batches: its id and version."""
    return (str(meta.get("doc_id", "")), str(meta.get("doc_version", "")))


def known_documents(rows: Iterable[dict]) -> set:
    """The (id, version) of every document in earlier Documents assets."""
    return {doc_key(r.get("meta") or {}) for r in rows}


def passages_by_id(rows: Iterable[dict]) -> Dict[str, dict]:
    return {r["meta"]["passage_id"]: r for r in rows}


def documents_by_id(rows: Iterable[dict]) -> Dict[str, List[dict]]:
    """Passage rows grouped by document, in passage order."""
    docs: Dict[str, List[dict]] = {}
    for r in rows:
        docs.setdefault(r["meta"]["doc_id"], []).append(r)
    for passages in docs.values():
        passages.sort(key=lambda r: int(r["meta"]["passage_id"].rsplit(":", 1)[1]))
    return docs


def passage_index(meta: dict) -> Optional[int]:
    try:
        return int(str(meta.get("passage_id", "")).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None

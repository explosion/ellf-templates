"""Gold labels: the correct mentions, links and relations of the evaluation documents.

Documents that come with gold labels are read in this format, one row per document:

    {"doc_id": "D1",
     "mentions": [{"passage": 0, "start": 10, "end": 18, "text": "Acme Inc", "type": "<TYPE>", "ids": ["E1"]}],
     "relations": [{"label": "<LABEL>", "head": "E1", "tail": "E2", "passage": 0}]}

"passage" is the index of the passage in the document; a mention with no "ids" is NIL. A
relation's "passage" can be left out when its group's scope is the whole document. The
evaluation tasks produce the same three things, so the scores and the gold swap read gold
labels the same way whichever way they were made.

"start" and "end" count characters in the passage's text as the Documents asset holds it,
after ``documents.clean``: runs of spaces and tabs collapsed, lines stripped, and, for a
document given as one "text", the lines of a paragraph joined. Offsets counted in the
original text move wherever it had extra whitespace. With the mention's "text", a mention
whose offsets don't give it is looked for nearby, whitespace aside, and moved there.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .mentions import Mention
from .schema import Schema



@dataclass
class GoldMention:
    mention: Mention
    ids: List[str]


@dataclass
class GoldReport:
    """What reading the gold labels found: mentions moved to their text, mentions with no
    text to check their offsets against, and every mention or relation that can't be used."""

    realigned: int = 0
    unchecked: int = 0
    problems: List[str] = field(default_factory=list)


def locate(text: str, start: int, end: int, wanted: str) -> Optional[Tuple[int, int]]:
    """The offsets of ``wanted`` in ``text``: ``start`` and ``end`` if they give it, else
    the occurrence nearest ``start``, whitespace aside, or None if there's none."""
    if text[start:end] == wanted:
        return start, end
    words = wanted.split()
    if not words:
        return None
    pattern = re.compile(r"\s+".join(re.escape(w) for w in words))
    found = [(abs(m.start() - start), m.start(), m.end()) for m in pattern.finditer(text)]
    return min(found)[1:] if found else None


def relation_key(group: str, where: str, head: str, tail: str, directed: bool) -> Tuple[str, str, str, str]:
    """A relation's identity: its group, where it's stated (the document for groups whose
    scope is the whole document, else the passage) and its two ends, in order if directed."""
    if not directed and tail < head:
        head, tail = tail, head
    return (group, where, head, tail)


def passage_problem(doc_passages: List[dict], index: int) -> Optional[str]:
    """Why a gold label's passage index can't be used, or None."""
    if not 0 <= index < len(doc_passages):
        return f"the document has no passage {index} (it has {len(doc_passages)})"
    if doc_passages[index]["meta"].get("kind") == "document":
        return f"passage {index} is a whole-document passage, which only shows the pairs of whole-document relations"
    return None


def gold_mentions(
    rows: Iterable[dict], passages: Dict[str, List[dict]], schema: Schema, report: Optional[GoldReport] = None
) -> List[GoldMention]:
    """The gold mentions with their entries. ``passages`` are the Documents rows by document.

    Mentions that can't be placed in their passage are left out, and described in
    ``report`` if one is given.
    """
    report = report if report is not None else GoldReport()
    out = []
    for row in rows:
        doc_id = str(row["doc_id"])
        doc_passages = passages.get(doc_id) or []
        if not doc_passages:
            continue
        for i, m in enumerate(row.get("mentions") or []):
            if m["type"] not in schema.entity_types:
                continue
            where = f"document {doc_id}, mention {i}"
            index = int(m.get("passage", 0))
            problem = passage_problem(doc_passages, index)
            if problem:
                report.problems.append(f"{where}: {problem}")
                continue
            p = doc_passages[index]
            start, end = int(m["start"]), int(m["end"])
            if m.get("text"):
                found = locate(p["text"], start, end, str(m["text"]))
                if found is None:
                    report.problems.append(f"{where}: {m['text']!r} isn't in passage {index} ({p['text'][max(0, start - 20) : end + 20]!r})")
                    continue
                if found != (start, end):
                    report.realigned += 1
                start, end = found
            else:
                report.unchecked += 1
                if not 0 <= start < end <= len(p["text"]):
                    report.problems.append(f"{where}: {start}-{end} isn't a span of passage {index}, which has {len(p['text'])} characters")
                    continue
            out.append(
                GoldMention(
                    mention=Mention(
                        doc_id=doc_id,
                        passage_id=p["meta"]["passage_id"],
                        start=start,
                        end=end,
                        text=p["text"][start:end],
                        type=m["type"],
                    ),
                    ids=[str(i) for i in m.get("ids") or []],
                )
            )
    return out


def gold_relations(
    rows: Iterable[dict], passages: Dict[str, List[dict]], schema: Schema, report: Optional[GoldReport] = None
) -> Dict[Tuple[str, str, str, str], Set[str]]:
    """Gold labels per relation key: one, or several in a group whose labels aren't
    exclusive. Pairs with no gold relation are NONE. Relations whose passage the document
    doesn't have are left out, and described in ``report`` if one is given."""
    report = report if report is not None else GoldReport()
    out: Dict[Tuple[str, str, str, str], Set[str]] = defaultdict(set)
    for row in rows:
        doc_id = str(row["doc_id"])
        doc_passages = passages.get(doc_id) or []
        for i, r in enumerate(row.get("relations") or []):
            group = schema.relation_for_label(r["label"])
            if group is None:
                continue
            if group.scope == "document":
                where = doc_id
            else:
                if r.get("passage") is None:
                    continue
                index = int(r["passage"])
                problem = passage_problem(doc_passages, index)
                if problem:
                    if doc_passages:
                        report.problems.append(f"document {doc_id}, relation {i}: {problem}")
                    continue
                where = doc_passages[index]["meta"]["passage_id"]
            out[relation_key(group.name, where, str(r["head"]), str(r["tail"]), group.directed)].add(r["label"])
    return dict(out)


def spans_examples(
    gold: Iterable[GoldMention], passages_by_id: Dict[str, dict], passage_ids: Iterable[str] = ()
) -> List[dict]:
    """The gold mentions as answers to the mentions task: one per passage that has any, and
    one with no spans for each of ``passage_ids`` that has none, since a gold document's
    empty passages are gold too: marking anything there is a mistake."""
    by_passage: Dict[str, List[Mention]] = defaultdict(list)
    for g in gold:
        by_passage[g.mention.passage_id].append(g.mention)
    for pid in passage_ids:
        by_passage.setdefault(pid, [])
    rows = []
    for pid, mentions in by_passage.items():
        p = passages_by_id[pid]
        spans = [{"start": m.start, "end": m.end, "label": m.type} for m in sorted(mentions, key=lambda m: m.start)]
        rows.append({"text": p["text"], "meta": p["meta"], "spans": spans, "answer": "accept"})
    return rows


def ids_by_overlap(gold: Iterable[GoldMention]):
    """A lookup from a mention key to its gold entries: by exact offsets, else the gold
    mention of the same type that overlaps it most in the same passage (gold spans that
    ended inside a token are widened before labelling)."""
    exact: Dict[Tuple, List[str]] = {}
    by_passage: Dict[Tuple[str, str], List[Tuple[int, int, List[str]]]] = defaultdict(list)
    for g in gold:
        m = g.mention
        exact[m.key] = g.ids
        by_passage[(m.passage_id, m.type)].append((m.start, m.end, g.ids))

    def lookup(key: Tuple) -> Optional[List[str]]:
        if key in exact:
            return exact[key]
        pid, start, end, type_ = key
        best, overlap = None, 0
        for s, e, ids in by_passage.get((pid, type_), ()):
            o = min(e, end) - max(s, start)
            if o > overlap:
                best, overlap = ids, o
        return best

    return lookup


def link_answers(gold: Iterable[GoldMention]) -> Dict[Tuple, List[str]]:
    """Gold entries by mention key; [] is NIL."""
    return {g.mention.key: g.ids for g in gold}


def doc_entries(gold: Iterable[GoldMention]) -> Dict[str, set]:
    """The set of (type, entry) each document links to, for document-level linking scores."""
    out: Dict[str, set] = defaultdict(set)
    for g in gold:
        for i in g.ids:
            out[g.mention.doc_id].add((g.mention.type, i))
    return out

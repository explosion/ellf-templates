"""Relation pairs: one row per pair of entities the schema allows, in a passage or a document.

Each mention becomes a node: the entries it's linked to, a NIL node (grouped by name across
documents) or nothing, as the schema says for its type; a mention of a type that isn't
linked is a node named by its text. Then, for every relation group, each pair of nodes
whose types the group allows becomes one row, with every mention of both ends marked:
the head ``[[like this]]`` and the tail ``{{like this}}``, or both ``[[like this]]`` when the
relation has no direction. Conditions found by the group's patterns go in ``meta``.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .linking import normalise
from .mentions import Mention
from .schema import RelationGroup, Schema

HEAD_MARKS = ("[[", "]]")
TAIL_MARKS = ("{{", "}}")


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    name: str
    nil: bool = False


def nil_node(type_: str, text: str, ignore: Sequence[str] = ()) -> Node:
    norm = normalise(text, ignore) or text.lower()
    return Node(id=f"NIL:{type_}:{norm}", type=type_, name=text, nil=True)


def mention_nodes(
    mentions: Iterable[Mention],
    groups: Iterable[dict],
    resolved: Dict[str, Tuple[List[str], str]],
    schema: Schema,
    entry_names: Dict[str, str],
    by_mention_ids: Optional[Dict[Tuple[str, int, int], List[str]]] = None,
) -> Dict[Tuple, List[Node]]:
    """Each mention's nodes, by mention key. Mentions whose group isn't decided yet are
    left out. ``by_mention_ids`` (from ``linking.mention_answers``) overrides a mention's
    group: the entries it was linked to on its own."""
    by_mention: Dict[Tuple, str] = {}
    for g in groups:
        for passage_id, start, end in g["mentions"]:
            by_mention[(passage_id, start, end, g["type"])] = g["group_id"]
    out: Dict[Tuple, List[Node]] = {}
    for m in mentions:
        etype = schema.entity_types.get(m.type)
        if etype is None:
            continue
        if not etype.linked:
            out[m.key] = [text_node(m, etype)]
            continue
        gid = by_mention.get(m.key)
        if gid is None or gid not in resolved:
            continue
        ids, _ = resolved[gid]
        own = (by_mention_ids or {}).get((m.passage_id, m.start, m.end))
        if own is not None:
            ids = own
        if ids:
            out[m.key] = [Node(id=i, type=m.type, name=entry_names.get(i, i)) for i in ids]
        elif etype.nil == "node":
            out[m.key] = [nil_node(m.type, m.text, etype.ignore_words)]
    return out


def text_node(m: Mention, etype) -> Node:
    """The node of a mention whose type isn't linked: named by its text."""
    norm = normalise(m.text, etype.ignore_words) or m.text.lower()
    return Node(id=f"{m.type}:{norm}", type=m.type, name=m.text)


def gold_ids_of_text_nodes(gold, schema: Schema) -> Dict[str, set]:
    """For types that aren't linked, which gold ids each text node stands for, so gold
    relations named by those ids can be matched to the graph's nodes."""
    out: Dict[str, set] = defaultdict(set)
    for g in gold:
        etype = schema.entity_types[g.mention.type]
        if not etype.linked and g.ids:
            out[text_node(g.mention, etype).id].update(g.ids)
    return out


def gold_nodes(gold, schema: Schema, entry_names: Dict[str, str]) -> Dict[Tuple, List[Node]]:
    """Each gold mention's nodes, from its gold entries, by mention key."""
    out: Dict[Tuple, List[Node]] = {}
    for g in gold:
        m = g.mention
        etype = schema.entity_types[m.type]
        if not etype.linked:
            out[m.key] = [text_node(m, etype)]
        elif g.ids:
            out[m.key] = [Node(id=i, type=m.type, name=entry_names.get(i, i)) for i in g.ids]
        elif etype.nil == "node":
            out[m.key] = [nil_node(m.type, m.text, etype.ignore_words)]
    return out


def _mark_both(text: str, head: List[Tuple[int, int]], tail: List[Tuple[int, int]], directed: bool) -> Tuple[str, List[dict]]:
    marks = [(s, e, "head") for s, e in head] + [(s, e, "tail") for s, e in tail]
    marks.sort()
    out, pos, spans = [], 0, []
    length = 0
    for start, end, role in marks:
        if start < pos:
            continue
        open_, close = HEAD_MARKS if (role == "head" or not directed) else TAIL_MARKS
        before = text[pos:start]
        out.append(before)
        length += len(before)
        out.append(open_)
        length += len(open_)
        spans.append({"start": length, "end": length + (end - start), "role": role})
        out.append(text[start:end])
        length += end - start
        out.append(close)
        length += len(close)
        pos = end
    out.append(text[pos:])
    return "".join(out), spans


def pair_id(group: str, doc_id: str, where: str, head: str, tail: str) -> str:
    return hashlib.sha1("\t".join([group, doc_id, where, head, tail]).encode("utf-8")).hexdigest()[:16]


def document_offsets(passages: List[dict]) -> Tuple[Optional[dict], Dict[str, int]]:
    """A document's "document" passage, and where each other passage starts in its text.

    The document passage is the other passages joined by blank lines, as ``parse_document``
    builds it.
    """
    whole = next((p for p in passages if p["meta"].get("kind") == "document"), None)
    offsets, pos = {}, 0
    for p in passages:
        if p["meta"].get("kind") == "document":
            continue
        offsets[p["meta"]["passage_id"]] = pos
        pos += len(p["text"]) + 2
    return whole, offsets


def pair_rows(
    group: RelationGroup,
    docs: Dict[str, List[dict]],
    mentions: Iterable[Mention],
    nodes: Dict[Tuple, List[Node]],
) -> List[dict]:
    """The candidate pairs of one relation group, as rows for its labelling task."""
    patterns = group.condition_patterns()
    by_doc: Dict[str, List[Mention]] = defaultdict(list)
    for m in mentions:
        if m.key in nodes:
            by_doc[m.doc_id].append(m)
    rows = []
    for doc_id, doc_mentions in sorted(by_doc.items()):
        passages = docs.get(doc_id, [])
        if not passages:
            continue
        by_id = {p["meta"]["passage_id"]: p for p in passages}
        if group.scope == "document":
            whole, offsets = document_offsets(passages)
            if whole is None:
                continue
            units = {whole["meta"]["passage_id"]: (whole, [])}
            for m in doc_mentions:
                if m.passage_id == whole["meta"]["passage_id"]:
                    units[m.passage_id][1].append((m, m.start, m.end))
                elif m.passage_id in offsets:
                    shift = offsets[m.passage_id]
                    units[whole["meta"]["passage_id"]][1].append((m, m.start + shift, m.end + shift))
        else:
            units = {}
            for m in doc_mentions:
                if m.passage_id in by_id and by_id[m.passage_id]["meta"].get("kind") != "document":
                    units.setdefault(m.passage_id, (by_id[m.passage_id], []))[1].append((m, m.start, m.end))
        for where, (passage, located) in units.items():
            spans_of: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
            node_of: Dict[str, Node] = {}
            for m, start, end in located:
                for node in nodes[m.key]:
                    spans_of[node.id].append((start, end))
                    node_of[node.id] = node
            ids = sorted(node_of)
            seen = set()
            for h in ids:
                for t in ids:
                    if h == t:
                        continue
                    head, tail = node_of[h], node_of[t]
                    if group.directed:
                        if not (head.type in group.head and tail.type in group.tail):
                            continue
                    else:
                        if not group.allows(head.type, tail.type) or (t, h) in seen:
                            continue
                    seen.add((h, t))
                    text, spans = _mark_both(passage["text"], spans_of[h], spans_of[t], group.directed)
                    if group.directed:
                        header = f"[[ ]] {head.name} ({head.type})    {{{{ }}}} {tail.name} ({tail.type})"
                    else:
                        header = f"[[ ]] {head.name} ({head.type}), {tail.name} ({tail.type})"
                    found = sorted(name for name, rx in patterns.items() if rx.search(passage["text"]))
                    rows.append(
                        {
                            "text": header + "\n\n" + text,
                            "spans": [
                                {
                                    "start": s["start"] + len(header) + 2,
                                    "end": s["end"] + len(header) + 2,
                                    "label": head.type if s["role"] == "head" else tail.type,
                                }
                                for s in spans
                            ],
                            "meta": {
                                "group": group.name,
                                "pair_id": pair_id(group.name, doc_id, where, h, t),
                                "doc_id": doc_id,
                                "passage_id": where,
                                "doc_version": passage["meta"].get("doc_version", ""),
                                "doc_date": passage["meta"].get("doc_date", ""),
                                "head_id": h,
                                "head_type": head.type,
                                "head_name": head.name,
                                "tail_id": t,
                                "tail_type": tail.type,
                                "tail_name": tail.name,
                                "conditions": found,
                            },
                        }
                    )
    return rows

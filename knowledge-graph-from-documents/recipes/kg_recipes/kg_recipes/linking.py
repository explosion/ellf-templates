"""Entity linking: each mention to entries in the entity list, or to NIL.

The entity list has one entry per line:

    {"id": "E1", "type": "<TYPE>", "name": "...", "aliases": ["..."], "description": "..."}

Mentions with the same text and type in one document are one *mention group*: they're
linked once, and the answer carries to all of them. For each group, candidates are looked
up by name, other names and approximate match, among entries of the mention's type only.
A group whose only candidate matches a name exactly is linked by rule; the rest become one
yes/no question per candidate. A group with no candidates is NIL.

Two optional sources add candidates to groups that no name matches exactly: names an LLM
proposes for the mention, looked up the same way, and the broader entries of the
candidates found, when the list gives them (``"broader": ["<id>", ...]``). Which ones a
project uses is decided from the evaluation: ``score.py linking`` reports which source
found the right entry.

After the links are settled, ``fix_rows`` asks again where the answers leave a group
unresolved: a group whose every candidate was rejected gets a wider search, and a group
given more than one entry of a type that links to one gets a question per mention. Answers
about a single mention carry ``mention_key`` in their ``meta`` and override its group's.
"""

import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .mentions import Mention, abbreviations
from .schema import EntityType, Schema

NON_WORD_RE = re.compile(r"[^\w]+")
APPROXIMATE_MIN = 0.6

MARK_OPEN, MARK_CLOSE = "[[", "]]"


@dataclass
class Entry:
    id: str
    type: str
    name: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    broader: List[str] = field(default_factory=list)


@dataclass
class Candidate:
    id: str
    name: str
    match: str  # "name", "alias", "llm", "approximate" or "broader"
    score: float


MATCH_ORDER = {"name": 0, "alias": 1, "llm": 2, "approximate": 3, "broader": 4}


@dataclass
class MentionGroup:
    group_id: str
    doc_id: str
    type: str
    text: str
    mentions: List[Mention]
    candidates: List[Candidate] = field(default_factory=list)
    expanded: str = ""  # the long form, if the text is an abbreviation the document defines

    @property
    def rule_ids(self) -> Optional[List[str]]:
        """The entries the rule links this group to, [] for NIL, or None to ask."""
        if not self.candidates:
            return []
        if len(self.candidates) == 1 and self.candidates[0].match in ("name", "alias"):
            return [self.candidates[0].id]
        return None


def normalise(text: str, ignore: Sequence[str] = ()) -> str:
    """Lower case, accents and punctuation removed, words in ``ignore`` dropped."""
    if not text.isascii():
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
    words = [w for w in NON_WORD_RE.sub(" ", text.lower()).split() if w not in ignore]
    return " ".join(words)


def _variants(norm: str) -> Set[str]:
    """The normalised form, and without a final plural s."""
    out = {norm}
    if len(norm) > 4 and norm.endswith("s") and not norm.endswith("ss"):
        out.add(norm[:-1])
    return out


def _trigrams(norm: str) -> Set[str]:
    padded = f"  {norm} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def similarity(a: str, b: str) -> float:
    """Share of trigrams two normalised names have in common."""
    ga, gb = _trigrams(a), _trigrams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


class EntityList:
    """The entries, indexed for lookup by type in a SQLite file on the job's own disk.

    Lists can hold hundreds of thousands of entries with several names each, which is too
    much to index in memory. Exact lookups use the normalised names; approximate ones
    score only the names that share the mention's rarest words.
    """

    MAX_SCORED = 300

    def __init__(self, schema: Schema, path: Optional[str] = None):
        self.schema = schema
        self.path = path or tempfile.mkstemp(prefix="kg-entities-", suffix=".sqlite")[1]
        self.db = sqlite3.connect(self.path)
        self.db.executescript(
            """
            PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
            CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, type TEXT, name TEXT, aliases TEXT, description TEXT, broader TEXT);
            CREATE TABLE IF NOT EXISTS names (type TEXT, norm TEXT, id TEXT, match TEXT);
            CREATE TABLE IF NOT EXISTS words (type TEXT, word TEXT, norm TEXT);
            """
        )

    @classmethod
    def from_rows(cls, rows: Iterable[dict], schema: Schema, path: Optional[str] = None) -> "EntityList":
        self = cls(schema, path)
        entries, names, words = [], [], []
        for row in rows:
            if not row.get("id") or not row.get("type") or not row.get("name"):
                raise ValueError(f"Every entry needs an 'id', a 'type' and a 'name': {row}")
            type_ = str(row["type"])
            if type_ not in schema.entity_types:
                continue
            id_, name = str(row["id"]), str(row["name"])
            aliases = [str(a) for a in row.get("aliases") or []]
            broader = [str(b) for b in row.get("broader") or []]
            entries.append((id_, type_, name, json.dumps(aliases), str(row.get("description") or ""), json.dumps(broader)))
            ignore = schema.entity_types[type_].ignore_words
            seen = set()
            for match, values in (("name", [name]), ("alias", aliases)):
                for value in values:
                    norm = normalise(value, ignore)
                    if not norm or norm in seen:
                        continue
                    seen.add(norm)
                    for v in _variants(norm):
                        names.append((type_, v, id_, match))
                    for w in set(norm.split()):
                        words.append((type_, w, norm))
            if len(names) > 200_000:
                self._insert(entries, names, words)
                entries, names, words = [], [], []
        self._insert(entries, names, words)
        self.db.executescript(
            """
            CREATE INDEX IF NOT EXISTS names_lookup ON names (type, norm);
            CREATE INDEX IF NOT EXISTS words_lookup ON words (type, word);
            CREATE TABLE IF NOT EXISTS word_counts AS SELECT type, word, COUNT(*) AS n FROM words GROUP BY type, word;
            CREATE INDEX IF NOT EXISTS word_counts_lookup ON word_counts (type, word);
            """
        )
        self.db.commit()
        return self

    def _insert(self, entries, names, words) -> None:
        self.db.executemany("INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?, ?)", entries)
        self.db.executemany("INSERT INTO names VALUES (?, ?, ?, ?)", names)
        self.db.executemany("INSERT INTO words VALUES (?, ?, ?)", words)

    def __len__(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def entry(self, id_: str) -> Entry:
        row = self.db.execute("SELECT id, type, name, aliases, description, broader FROM entries WHERE id = ?", (id_,)).fetchone()
        if row is None:
            raise KeyError(id_)
        return Entry(id=row[0], type=row[1], name=row[2], aliases=json.loads(row[3]), description=row[4], broader=json.loads(row[5]))

    def entry_or_id(self, id_: str, type_: str) -> Entry:
        """The entry, or an entry holding only the id when the list doesn't have it, e.g. a
        gold entry from another version of the list."""
        return self.entry(id_) if self.has(id_) else Entry(id=id_, type=type_, name=id_)

    def has(self, id_: str) -> bool:
        return self.db.execute("SELECT 1 FROM entries WHERE id = ?", (id_,)).fetchone() is not None

    def _ids_for(self, type_: str, norm: str) -> Dict[str, str]:
        found: Dict[str, str] = {}
        for id_, match in self.db.execute("SELECT id, match FROM names WHERE type = ? AND norm = ?", (type_, norm)):
            if found.get(id_) != "name":
                found[id_] = match
        return found

    def exact(self, type_: str, text: str) -> Dict[str, str]:
        ignore = self.schema.entity_types[type_].ignore_words
        found: Dict[str, str] = {}
        for v in _variants(normalise(text, ignore)):
            for id_, match in self._ids_for(type_, v).items():
                if found.get(id_) != "name":
                    found[id_] = match
        return found

    def approximate(self, type_: str, text: str, limit: int) -> List[Tuple[str, float]]:
        """Entries whose names are most like the text, best first."""
        norm = normalise(text, self.schema.entity_types[type_].ignore_words)
        if len(norm) < 4:
            return []
        counts = []
        for w in set(norm.split()):
            row = self.db.execute("SELECT n FROM word_counts WHERE type = ? AND word = ?", (type_, w)).fetchone()
            if row:
                counts.append((row[0], w))
        others: Set[str] = set()
        for _, w in sorted(counts):
            for (other,) in self.db.execute(
                "SELECT norm FROM words WHERE type = ? AND word = ? LIMIT ?", (type_, w, self.MAX_SCORED)
            ):
                others.add(other)
            if len(others) >= self.MAX_SCORED:
                break
        scored = sorted(((similarity(norm, o), o) for o in others), reverse=True)
        best: Dict[str, float] = {}
        for score, other in scored:
            if score < APPROXIMATE_MIN:
                break
            for id_ in self._ids_for(type_, other):
                best.setdefault(id_, score)
            if len(best) >= limit:
                break
        return list(best.items())[:limit]

    def candidates(self, type_: str, forms: Sequence[str], limit: int, exclude: Iterable[str] = ()) -> List[Candidate]:
        found: Dict[str, Candidate] = {}
        skip = set(exclude)
        for form in forms:
            for id_, match in self.exact(type_, form).items():
                if id_ not in skip and (id_ not in found or (match == "name" and found[id_].match != "name")):
                    found[id_] = Candidate(id=id_, name=self.entry(id_).name, match=match, score=1.0)
        if len(found) < limit:
            for form in forms:
                for id_, score in self.approximate(type_, form, limit + len(skip)):
                    if id_ not in found and id_ not in skip:
                        found[id_] = Candidate(id=id_, name=self.entry(id_).name, match="approximate", score=round(score, 3))
        return sorted(found.values(), key=lambda c: (MATCH_ORDER[c.match], -c.score, c.name))[:limit]

    def expand(
        self,
        type_: str,
        found: List[Candidate],
        limit: int,
        proposed: Sequence[str] = (),
        broader: bool = False,
        exclude: Iterable[str] = (),
    ) -> List[Candidate]:
        """``found`` plus the entries of names an LLM proposed and the broader entries of
        everything found, up to ``limit``."""
        out = {c.id: c for c in found}
        skip = set(exclude)
        if proposed:
            for c in self.candidates(type_, proposed, limit, exclude=skip | set(out)):
                out.setdefault(c.id, Candidate(id=c.id, name=c.name, match="llm", score=c.score))
        if broader:
            for c in list(out.values()):
                for id_ in self.entry(c.id).broader:
                    if id_ not in out and id_ not in skip and self.has(id_) and self.entry(id_).type == type_:
                        out[id_] = Candidate(id=id_, name=self.entry(id_).name, match="broader", score=c.score)
        return sorted(out.values(), key=lambda c: (MATCH_ORDER[c.match], -c.score, c.name))[:limit]


def group_id(doc_id: str, type_: str, norm: str) -> str:
    return hashlib.sha1(f"{doc_id}\t{type_}\t{norm}".encode("utf-8")).hexdigest()[:16]


def mention_groups(
    mentions: Iterable[Mention], schema: Schema, doc_texts: Dict[str, str]
) -> List[MentionGroup]:
    """Mentions grouped by document, type and normalised text, for linked types only."""
    groups: Dict[str, MentionGroup] = {}
    abbrevs: Dict[str, Dict[str, str]] = {}
    for m in mentions:
        etype = schema.entity_types.get(m.type)
        if etype is None or not etype.linked:
            continue
        norm = normalise(m.text, etype.ignore_words) or m.text.lower()
        gid = group_id(m.doc_id, m.type, norm)
        if gid not in groups:
            if m.doc_id not in abbrevs:
                abbrevs[m.doc_id] = abbreviations(doc_texts.get(m.doc_id, ""))
            groups[gid] = MentionGroup(
                group_id=gid,
                doc_id=m.doc_id,
                type=m.type,
                text=m.text,
                mentions=[],
                expanded=abbrevs[m.doc_id].get(m.text.strip(), ""),
            )
        groups[gid].mentions.append(m)
    return list(groups.values())


#: Proposes names a mention's entry could be listed under: (group, context) -> names.
Propose = Callable[["MentionGroup", str], List[str]]


def forms_of(g: "MentionGroup") -> List[str]:
    return [g.text] + ([g.expanded] if g.expanded else [])


def add_candidates(
    groups: Iterable[MentionGroup],
    entities: EntityList,
    schema: Schema,
    propose: Optional[Propose] = None,
    broader: bool = False,
    contexts: Optional[Dict[str, str]] = None,
) -> None:
    """Each group's candidates. Groups that no name matches exactly also get the optional
    sources: names ``propose`` returns, and broader entries."""
    for g in groups:
        limit = schema.entity_types[g.type].max_candidates
        g.candidates = entities.candidates(g.type, forms_of(g), limit)
        if any(c.match in ("name", "alias") for c in g.candidates) or not (propose or broader):
            continue
        proposed = propose(g, (contexts or {}).get(g.group_id, "")) if propose else []
        g.candidates = entities.expand(g.type, g.candidates, limit, proposed, broader)


def context_of(g: "MentionGroup", passages: Dict[str, dict], width: int = 300) -> str:
    """The text around the group's first mention."""
    m = g.mentions[0]
    text = passages[m.passage_id]["text"]
    return text[max(0, m.start - width) : m.end + width]


def proposal_prompt(g: "MentionGroup", etype: EntityType, context: str, n: int = 5) -> str:
    level = f" Entries are at this level: {etype.level}." if etype.level else ""
    expanded = f' The document defines "{g.text}" as "{g.expanded}".' if g.expanded else ""
    return (
        f'A document mentions "{g.text}", an entity of type {etype.name}: {etype.description}{level}{expanded}\n'
        f"The text around it:\n{context}\n\n"
        f"List up to {n} names under which this entity is most likely listed in a reference list of "
        f"{etype.name} entries: its preferred name first, then other common names. One name per line, "
        "nothing else."
    )


def mark(text: str, spans: Iterable[Tuple[int, int]], open_: str = MARK_OPEN, close: str = MARK_CLOSE) -> Tuple[str, List[dict]]:
    """The text with each span marked, and the spans' offsets in the marked text."""
    out, pos, shift, marked = [], 0, 0, []
    for start, end in sorted(set(spans)):
        if start < pos:
            continue
        out.append(text[pos:start])
        shift_start = start + shift + len(open_)
        out.append(open_ + text[start:end] + close)
        marked.append({"start": shift_start, "end": shift_start + (end - start)})
        shift += len(open_) + len(close)
        pos = end
    out.append(text[pos:])
    return "".join(out), marked


#: Characters of text shown on each side of the marked mention in a link question.
CONTEXT = 400


def question_text(header: List[str], text: str, spans: Iterable[Tuple[int, int]], context: int = CONTEXT) -> Tuple[str, List[dict]]:
    """A question: the candidate's lines first, so they're seen without scrolling, then the
    text around the first marked mention (``context`` characters each side, 0 for all of
    it), with the spans' offsets in the result."""
    text, marked = mark(text, spans)
    start, end = 0, len(text)
    if context and marked:
        start = max(0, marked[0]["start"] - len(MARK_OPEN) - context)
        end = min(len(text), marked[0]["end"] + len(MARK_CLOSE) + context)
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
    before = "\n".join(header) + "\n\n" + ("… " if start > 0 else "")
    body = before + text[start:end] + (" …" if end < len(text) else "")
    shift = len(before) - start
    kept = [{"start": m["start"] + shift, "end": m["end"] + shift} for m in marked if m["start"] >= start and m["end"] <= end]
    return body, kept


def candidate_lines(entry: Entry, g: MentionGroup) -> List[str]:
    lines = [f"Candidate: {entry.name} ({entry.type})"]
    if entry.aliases:
        lines.append("Other names: " + "; ".join(entry.aliases[:12]))
    if entry.description:
        lines.append("Description: " + entry.description)
    if g.expanded:
        lines.append(f"The document defines {g.text} as: {g.expanded}")
    return lines


def question_rows(
    groups: Iterable[MentionGroup],
    entities: EntityList,
    passages: Dict[str, dict],
    list_version: str = "",
    always: bool = False,
    extra_meta: Optional[dict] = None,
    context: int = CONTEXT,
) -> List[dict]:
    """One yes/no question per mention group and candidate, for groups the rule doesn't
    link, or for every group with ``always``."""
    rows = []
    for g in groups:
        if g.rule_ids is not None and not always:
            continue
        first = g.mentions[0]
        passage = passages[first.passage_id]
        spans = [(m.start, m.end) for m in g.mentions if m.passage_id == first.passage_id]
        for rank, c in enumerate(g.candidates):
            entry = entities.entry(c.id)
            text, marked = question_text(candidate_lines(entry, g), passage["text"], spans, context)
            rows.append(
                {
                    "text": text,
                    "spans": [{**s, "label": g.type} for s in marked],
                    "meta": {
                        "group_id": g.group_id,
                        "doc_id": g.doc_id,
                        "passage_id": first.passage_id,
                        "doc_version": passage["meta"].get("doc_version", ""),
                        "mention": g.text,
                        "mention_type": g.type,
                        "candidate_id": c.id,
                        "candidate_name": entry.name,
                        "match": c.match,
                        "score": c.score,
                        "rank": rank,
                        "candidates": len(g.candidates),
                        "list_version": list_version,
                        **(extra_meta or {}),
                    },
                }
            )
    return rows


def group_rows(groups: Iterable[MentionGroup], list_version: str = "") -> List[dict]:
    """One row per mention group: its mentions, candidates and the rule's link, if any."""
    rows = []
    for g in groups:
        rows.append(
            {
                "group_id": g.group_id,
                "doc_id": g.doc_id,
                "type": g.type,
                "text": g.text,
                "expanded": g.expanded,
                "mentions": [[m.passage_id, m.start, m.end] for m in g.mentions],
                "candidates": [{"id": c.id, "name": c.name, "match": c.match, "score": c.score} for c in g.candidates],
                "rule_ids": g.rule_ids,
                "list_version": list_version,
            }
        )
    return rows


def resolve(group_rows_: Iterable[dict], answers: Iterable[Tuple[dict, Optional[str]]]) -> Dict[str, Tuple[List[str], str]]:
    """Each group's entries and how they were decided: the accepted answers, or the rule.

    ``answers`` are settled yes/no answers to the questions; a group with questions but no
    settled answers yet is left out, so it isn't linked until it's decided. Answers about a
    group override its rule: that's how gold links replace every other decision.
    """
    yes: Dict[str, Set[str]] = defaultdict(set)
    answered: Set[str] = set()
    for eg, _ in answers:
        meta = eg.get("meta") or {}
        gid = meta.get("group_id")
        if not gid or meta.get("mention_key") or eg.get("answer") not in ("accept", "reject"):
            continue
        answered.add(gid)
        if eg.get("answer") == "accept":
            yes[gid].add(meta["candidate_id"])
    out: Dict[str, Tuple[List[str], str]] = {}
    for row in group_rows_:
        gid = row["group_id"]
        if gid in answered:
            out[gid] = (sorted(i for i in yes[gid] if i), "answers")
        elif row.get("rule_ids") is not None:
            out[gid] = (list(row["rule_ids"]), "rule")
    return out


MentionKey = Tuple[str, int, int]


def mention_answers(answers: Iterable[Tuple[dict, Optional[str]]]) -> Dict[MentionKey, List[str]]:
    """The entries of single mentions, from answers about one mention (``meta.mention_key``):
    its accepted candidates, or [] when every one was rejected."""
    yes: Dict[MentionKey, Set[str]] = defaultdict(set)
    answered: Set[MentionKey] = set()
    for eg, _ in answers:
        meta = eg.get("meta") or {}
        key = meta.get("mention_key")
        if not key or eg.get("answer") not in ("accept", "reject"):
            continue
        key = (str(key[0]), int(key[1]), int(key[2]))
        answered.add(key)
        if eg.get("answer") == "accept" and meta.get("candidate_id"):
            yes[key].add(meta["candidate_id"])
    return {k: sorted(yes[k]) for k in answered}


def group_from_row(row: dict, passages: Dict[str, dict]) -> MentionGroup:
    """A mention group as ``group_rows`` wrote it, with its mentions' text from the passages."""
    mentions = []
    for passage_id, start, end in row["mentions"]:
        text = passages[passage_id]["text"][start:end] if passage_id in passages else row["text"]
        mentions.append(Mention(row["doc_id"], passage_id, start, end, text, row["type"]))
    candidates = [Candidate(c["id"], c["name"], c["match"], c["score"]) for c in row.get("candidates") or []]
    return MentionGroup(row["group_id"], row["doc_id"], row["type"], row["text"], mentions, candidates, row.get("expanded", ""))


def fix_rows(
    group_rows_: Iterable[dict],
    answers: List[Tuple[dict, Optional[str]]],
    entities: EntityList,
    schema: Schema,
    passages: Dict[str, dict],
    wider: int = 15,
    propose: Optional[Propose] = None,
    broader: bool = False,
    list_version: str = "",
    context: int = CONTEXT,
) -> Tuple[List[dict], Dict[str, int]]:
    """Questions for what the settled answers leave unresolved, and how many of each kind.

    - *retry*: every candidate of the group was rejected. A wider search (up to ``wider``
      candidates, plus the optional sources), without the candidates already asked about.
    - *split*: the group was linked to more than one entry, but its type links a mention
      to one. One question per mention and entry.
    """
    resolved = resolve(group_rows_, answers)
    by_mention = mention_answers(answers)
    rows: List[dict] = []
    counts = {"retry": 0, "split": 0, "unchanged": 0}
    for row in group_rows_:
        decided = resolved.get(row["group_id"])
        etype = schema.entity_types.get(row["type"])
        if decided is None or etype is None or not etype.linked:
            continue
        ids, how = decided
        g = group_from_row(row, passages)
        if not ids and how == "answers":
            asked = {c.id for c in g.candidates}
            found = entities.candidates(g.type, forms_of(g), wider, exclude=asked)
            proposed = propose(g, context_of(g, passages)) if propose else []
            g.candidates = entities.expand(g.type, found, wider, proposed, broader, exclude=asked)
            if not g.candidates:
                counts["unchanged"] += 1
                continue
            counts["retry"] += 1
            rows.extend(question_rows([g], entities, passages, list_version, always=True, extra_meta={"fix": "retry"}, context=context))
        elif len(ids) > 1 and not etype.multiple and len(g.mentions) > 1:
            if all((m.passage_id, m.start, m.end) in by_mention for m in g.mentions):
                continue
            counts["split"] += 1
            for m in g.mentions:
                passage = passages[m.passage_id]
                for cid in ids:
                    entry = entities.entry_or_id(cid, g.type)
                    others = "; ".join(entities.entry_or_id(i, g.type).name for i in ids if i != cid)
                    header = [
                        f"Candidate: {entry.name} ({entry.type})",
                        f"This name was linked to more than one entry in the document. The other: {others}.",
                    ]
                    if entry.description:
                        header.append("Description: " + entry.description)
                    text, marked = question_text(header, passage["text"], [(m.start, m.end)], context)
                    rows.append(
                        {
                            "text": text,
                            "spans": [{**s, "label": g.type} for s in marked],
                            "meta": {
                                "group_id": g.group_id,
                                "mention_key": [m.passage_id, m.start, m.end],
                                "doc_id": g.doc_id,
                                "passage_id": m.passage_id,
                                "doc_version": passage["meta"].get("doc_version", ""),
                                "mention": m.text,
                                "mention_type": g.type,
                                "candidate_id": cid,
                                "candidate_name": entry.name,
                                "match": "split",
                                "list_version": list_version,
                                "fix": "split",
                            },
                        }
                    )
    return rows, counts


def gold_answers(
    groups: Iterable[MentionGroup],
    gold_ids: Dict[str, Set[str]],
    annotator: str = "gold",
    mention_ids: Optional[Dict[MentionKey, Set[str]]] = None,
) -> List[dict]:
    """Gold yes/no answers for every group: yes to its gold entries, no to its other
    candidates. A gold entry that isn't a candidate gets a yes of its own, so the gold
    graph holds the right entry even where the candidate search missed it; a gold NIL
    group gets one no, so it counts as decided. Where a group's mentions have different
    gold entries (``mention_ids``), each mention also gets answers of its own."""
    rows = []
    mention_ids = mention_ids or {}
    for g in groups:
        keys = [(m.passage_id, m.start, m.end) for m in g.mentions]
        per = {k: mention_ids[k] for k in keys if k in mention_ids}
        if len({frozenset(v) for v in per.values()}) > 1:
            every = set().union(*per.values())
            for key, right in per.items():
                for cid in sorted(every):
                    rows.append(
                        {
                            "text": f"{g.text} ({g.type}) at {key[0]} {key[1]}-{key[2]} = {cid}",
                            "label": "SAME",
                            "answer": "accept" if cid in right else "reject",
                            "meta": {"group_id": g.group_id, "mention_key": list(key), "doc_id": g.doc_id, "mention": g.text, "mention_type": g.type, "candidate_id": cid},
                            "_annotator_id": annotator,
                            "_session_id": annotator,
                        }
                    )
        right = gold_ids.get(g.group_id, set())
        cands = [c.id for c in g.candidates]
        decided = [(c, c in right) for c in cands] + [(i, True) for i in sorted(right - set(cands))]
        if not decided:
            decided = [("", False)]
        for cid, yes in decided:
            rows.append(
                {
                    "text": f"{g.text} ({g.type}) = {cid or 'NIL'}",
                    "label": "SAME",
                    "answer": "accept" if yes else "reject",
                    "meta": {"group_id": g.group_id, "doc_id": g.doc_id, "mention": g.text, "mention_type": g.type, "candidate_id": cid},
                    "_annotator_id": annotator,
                    "_session_id": annotator,
                }
            )
    return rows

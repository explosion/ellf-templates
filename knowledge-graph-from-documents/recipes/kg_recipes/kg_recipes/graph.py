"""Build the graph from the documents, the settled datasets and the schema, and load it.

Nodes: (:Entity {id, type, name, nil}), (:Document {doc_id, version, date, title, url}),
(:Passage {passage_id, doc_id, text, section, kind}).
Links: (:Document)-[:HAS_PASSAGE]->(:Passage), (:Passage)-[:MENTIONS {start, end, text}]->(:Entity),
and one relationship per relation label between entities, named by the label, carrying
the relation group, its evidence count, conditions, document versions and dates, and the
methods behind it. Each piece of evidence is an (:Evidence) node linked to its passage.
"""

import base64
import hashlib
import json
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import linking
from . import pairs as kg_pairs
from .data import Answer
from .mentions import Mention
from .schema import NONE, Schema

BATCH = 1000


@dataclass
class GraphRows:
    entities: List[dict] = field(default_factory=list)
    documents: List[dict] = field(default_factory=list)
    passages: List[dict] = field(default_factory=list)
    mentions: List[dict] = field(default_factory=list)
    links: List[dict] = field(default_factory=list)
    evidence: List[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{len(self.entities)} entities, {len(self.documents)} documents, {len(self.passages)} passages, "
            f"{len(self.mentions)} mentions, {len(self.links)} links from {len(self.evidence)} pieces of evidence"
        )


def chosen_labels(eg: dict) -> List[str]:
    """The labels of an accepted relation answer, NONE left out: one, or several in a group
    whose labels aren't exclusive."""
    if eg.get("answer") != "accept":
        return []
    return [l for l in dict.fromkeys(eg.get("accept") or []) if l != NONE]


def link_id(group: str, label: str, head: str, tail: str) -> str:
    return hashlib.sha1("\t".join([group, label, head, tail]).encode("utf-8")).hexdigest()[:16]


def relation_links(
    schema: Schema,
    settled: Iterable[Answer],
    labelled: Iterable[Answer] = (),
) -> Tuple[List[dict], List[dict]]:
    """Links and their evidence from settled relation answers.

    ``labelled`` are every labeller's answers, shown beside each piece of evidence.
    """
    others: Dict[str, Dict[str, Optional[str]]] = defaultdict(dict)
    for eg, who in labelled:
        pid = (eg.get("meta") or {}).get("pair_id")
        if pid:
            others[pid][who or "unknown"] = ", ".join(eg.get("accept") or []) if eg.get("answer") == "accept" else eg.get("answer")
    by_pair: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    seen_pairs = set()
    for eg, who in settled:
        meta = eg.get("meta") or {}
        if not meta.get("pair_id") or meta["pair_id"] in seen_pairs:
            continue
        labels = chosen_labels(eg)
        if labels:
            seen_pairs.add(meta["pair_id"])
        for label in labels:
            group = schema.relation_for_label(label)
            if group is None:
                continue
            by_pair[(group.name, meta["head_id"], meta["tail_id"])].append(
                {
                    "pair_id": meta["pair_id"],
                    "label": label,
                    "doc_id": meta.get("doc_id", ""),
                    "passage_id": meta.get("passage_id", ""),
                    "doc_version": meta.get("doc_version", ""),
                    "doc_date": meta.get("doc_date", ""),
                    "conditions": list(meta.get("conditions") or []),
                    "settled_by": who or "unknown",
                    "answers": json.dumps(others.get(meta["pair_id"], {}), sort_keys=True),
                    "ends": {
                        meta["head_id"]: (meta.get("head_type", ""), meta.get("head_name", meta["head_id"])),
                        meta["tail_id"]: (meta.get("tail_type", ""), meta.get("tail_name", meta["tail_id"])),
                    },
                }
            )
    links, evidence = [], []
    for (group_name, head, tail), items in by_pair.items():
        group = schema.relation(group_name)
        if group.combine == "latest":
            latest = max(i["doc_date"] for i in items)
            items = [i for i in items if i["doc_date"] == latest]
        labels = Counter(i["label"] for i in items)
        if group.combine == "majority":
            top = labels.most_common(1)[0][0]
            keep = {top}
        else:
            keep = set(labels)
        for label in sorted(keep):
            support = [i for i in items if i["label"] == label]
            lid = link_id(group_name, label, head, tail)
            links.append(
                {
                    "id": lid,
                    "label": label,
                    "group": group_name,
                    "head": head,
                    "tail": tail,
                    "evidence": len(support),
                    "conditions": sorted({c for i in support for c in i["conditions"]}),
                    "doc_versions": sorted({f"{i['doc_id']}@{i['doc_version']}" for i in support}),
                    "first_date": min(i["doc_date"] for i in support),
                    "last_date": max(i["doc_date"] for i in support),
                    "methods": sorted({i["settled_by"] for i in support}),
                    "ends": support[0]["ends"],
                }
            )
            for i in support:
                evidence.append({k: v for k, v in i.items() if k != "ends"} | {"link_id": lid})
    return links, evidence


def build(
    schema: Schema,
    passage_rows: List[dict],
    mentions: List[Mention],
    nodes: Dict[Tuple, List[kg_pairs.Node]],
    relation_settled: Iterable[Answer],
    relation_labelled: Iterable[Answer] = (),
    list_version: str = "",
) -> GraphRows:
    rows = GraphRows()
    docs: Dict[str, dict] = {}
    for p in passage_rows:
        m = p["meta"]
        docs.setdefault(
            m["doc_id"],
            {
                "doc_id": m["doc_id"],
                "version": m.get("doc_version", ""),
                "date": m.get("doc_date", ""),
                "title": m.get("title", ""),
                "url": m.get("url", ""),
            },
        )
        rows.passages.append(
            {
                "passage_id": m["passage_id"],
                "doc_id": m["doc_id"],
                "text": p["text"],
                "section": m.get("section", ""),
                "kind": m.get("kind", "paragraph"),
            }
        )
    rows.documents = list(docs.values())
    entities: Dict[str, dict] = {}
    for m in mentions:
        for node in nodes.get(m.key, []):
            entities.setdefault(
                node.id, {"id": node.id, "type": node.type, "name": node.name, "nil": node.nil, "list_version": list_version}
            )
            rows.mentions.append(
                {"passage_id": m.passage_id, "entity": node.id, "start": m.start, "end": m.end, "text": m.text}
            )
    rows.links, rows.evidence = relation_links(schema, relation_settled, relation_labelled)
    for link in rows.links:
        ends = link.pop("ends", {})
        for end in (link["head"], link["tail"]):
            if end not in entities:
                type_, name = ends.get(end, ("", end))
                entities[end] = {"id": end, "type": type_, "name": name, "nil": end.startswith("NIL:"), "list_version": list_version}
    rows.entities = list(entities.values())
    return rows


class Neo4jError(Exception):
    pass


class Neo4j:
    """The few calls the service makes to Neo4j's HTTP API, with the standard library."""

    def __init__(self, url: str, user: str, password: str, database: str = "neo4j") -> None:
        self.endpoint = f"{url.rstrip('/')}/db/{database}/tx/commit"
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Content-Type": "application/json", "Authorization": f"Basic {token}"}

    def run(self, statements: List[Tuple[str, Optional[dict]]], *, read_only: bool = False, timeout: float = 300) -> List[dict]:
        """Run statements in one transaction and return one ``{columns, rows}`` per statement."""
        body = {"statements": [{"statement": s, "parameters": p or {}} for s, p in statements]}
        headers = dict(self.headers)
        if read_only:
            # Neo4j refuses any write in a read transaction.
            headers["access-mode"] = "READ"
        req = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.load(resp)
        except urllib.error.HTTPError as e:
            raise Neo4jError(f"Neo4j answered {e.code}: {e.read()[:500].decode(errors='replace')}") from e
        if result.get("errors"):
            raise Neo4jError("; ".join(err.get("message", str(err)) for err in result["errors"]))
        return [{"columns": r["columns"], "rows": [d["row"] for d in r["data"]]} for r in result["results"]]

    def query(self, statement: str, read_only: bool = True, **params: Any) -> List[dict]:
        """Run one statement and return its rows as dicts."""
        result = self.run([(statement, params)], read_only=read_only)[0]
        return [dict(zip(result["columns"], row)) for row in result["rows"]]


SETUP = [
    "MATCH (n) DETACH DELETE n",
    "CREATE INDEX entity_id IF NOT EXISTS FOR (e:Entity) ON (e.id)",
    "CREATE INDEX document_id IF NOT EXISTS FOR (d:Document) ON (d.doc_id)",
    "CREATE INDEX passage_id IF NOT EXISTS FOR (p:Passage) ON (p.passage_id)",
    "CREATE INDEX evidence_link IF NOT EXISTS FOR (v:Evidence) ON (v.link_id)",
]
LOADS = [
    ("entities", "UNWIND $rows AS r CREATE (:Entity {id: r.id, type: r.type, name: r.name, nil: r.nil, list_version: r.list_version})"),
    ("documents", "UNWIND $rows AS r CREATE (:Document {doc_id: r.doc_id, version: r.version, date: r.date, title: r.title, url: r.url})"),
    (
        "passages",
        "UNWIND $rows AS r MATCH (d:Document {doc_id: r.doc_id}) "
        "CREATE (d)-[:HAS_PASSAGE]->(:Passage {passage_id: r.passage_id, doc_id: r.doc_id, text: r.text, section: r.section, kind: r.kind})",
    ),
    (
        "mentions",
        "UNWIND $rows AS r MATCH (p:Passage {passage_id: r.passage_id}) MATCH (e:Entity {id: r.entity}) "
        "CREATE (p)-[:MENTIONS {start: r.start, end: r.end, text: r.text}]->(e)",
    ),
    (
        "evidence",
        "UNWIND $rows AS r MATCH (p:Passage {passage_id: r.passage_id}) "
        "CREATE (p)-[:SUPPORTS]->(:Evidence {link_id: r.link_id, pair_id: r.pair_id, label: r.label, doc_id: r.doc_id, "
        "doc_version: r.doc_version, doc_date: r.doc_date, conditions: r.conditions, settled_by: r.settled_by, answers: r.answers})",
    ),
]
LINK = (
    "UNWIND $rows AS r MATCH (h:Entity {id: r.head}) MATCH (t:Entity {id: r.tail}) "
    "CREATE (h)-[:`{label}` {{id: r.id, group: r.group, evidence: r.evidence, conditions: r.conditions, "
    "doc_versions: r.doc_versions, first_date: r.first_date, last_date: r.last_date, methods: r.methods}}]->(t)"
)


def load(db: Neo4j, rows: GraphRows) -> None:
    """Replace everything in the database with ``rows``."""
    for statement in SETUP:
        db.run([(statement, None)])
    for name, statement in LOADS:
        items = getattr(rows, name)
        for i in range(0, len(items), BATCH):
            db.run([(statement, {"rows": items[i : i + BATCH]})])
    by_label: Dict[str, List[dict]] = defaultdict(list)
    for link in rows.links:
        by_label[link["label"]].append(link)
    for label, items in by_label.items():
        statement = LINK.replace("{label}", label).replace("{{", "{").replace("}}", "}")
        for i in range(0, len(items), BATCH):
            db.run([(statement, {"rows": items[i : i + BATCH]})])


def run_checks(db: Neo4j, schema: Schema) -> List[dict]:
    """Each check with the rows it returned; a check passes when it returns none."""
    results = []
    for check in schema.checks:
        try:
            found = db.query(check.cypher)
            results.append({"name": check.name, "description": check.description, "rows": found[:20], "count": len(found), "error": None})
        except Neo4jError as e:
            results.append({"name": check.name, "description": check.description, "rows": [], "count": 0, "error": str(e)})
    return results


@dataclass
class Sources:
    """Where the graph's data comes from: asset paths and dataset names."""

    schema: Schema
    documents: List[str]
    entity_list: str
    groups: List[str]
    mentions: List[str]
    links: List[str]
    relations: List[str]
    relations_labelled: List[str] = field(default_factory=list)
    list_version: str = ""


def assemble(sources: Sources) -> GraphRows:
    """Read every source and build the graph's rows."""
    from .data import read_assets, read_datasets, read_jsonl
    from .documents import passages_by_id
    from .mentions import mentions_from_answers

    passage_rows = read_assets(sources.documents)
    by_passage = passages_by_id(passage_rows)
    mentions = [m for m in mentions_from_answers(read_datasets(sources.mentions)) if m.passage_id in by_passage]
    group_rows = read_assets(sources.groups)
    link_answers = read_datasets(sources.links)
    resolved = linking.resolve(group_rows, link_answers)
    by_mention = linking.mention_answers(link_answers)
    wanted = {i for ids, _ in resolved.values() for i in ids} | {i for ids in by_mention.values() for i in ids}
    names = {r["id"]: r["name"] for r in read_jsonl(sources.entity_list) if r.get("id") in wanted}
    nodes = kg_pairs.mention_nodes(mentions, group_rows, resolved, sources.schema, names, by_mention)
    return build(
        sources.schema,
        passage_rows,
        mentions,
        nodes,
        read_datasets(sources.relations),
        read_datasets(sources.relations_labelled),
        sources.list_version,
    )

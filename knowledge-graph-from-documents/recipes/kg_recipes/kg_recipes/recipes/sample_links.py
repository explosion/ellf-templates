"""Action recipe that draws a random sample of the graph's links for a person to check.

The sample is drawn per relation label and grouped by document: whole documents are
drawn at random, and their links taken, until a label has enough. Each row shows the link
and every passage behind it; the link-check task asks whether the passages state it.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

import random
from collections import defaultdict
from typing import List, Optional

from prodigy.util import log

from ellf_recipes_sdk import Asset, Input, InputDataset, IntProps, OptionalProps, Output, Props, TextProps, action_recipe

from .. import schema as kg_schema
from ..data import write_jsonl
from ..documents import passages_by_id
from ..graph import Sources, assemble

SUBDIR = "kg_recipes"


@action_recipe(
    title="Sample links to check (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Draw a random sample of the graph's links per relation label, grouped by document, with the "
        "passages behind each, for a person to check: the precision of the graph's links."
    ),
    category="data",
    field_props={
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "documents": Props(title="Documents", description="The Documents assets, as given to the service."),
        "entity_list": Props(title="Entity list", description="The entity list, as given to the service."),
        "groups": Props(title="Mention groups", description="The mention groups assets, as given to the service."),
        "mentions": Props(title="Settled mentions", description="As given to the service."),
        "links": OptionalProps(title="Settled links", optional_title="Use settled link answers", description="As given to the service."),
        "relations": Props(title="Settled relations", description="As given to the service."),
        "per_label": IntProps(title="Links per label", description="How many links to check for each relation label.", min=1),
        "seed": IntProps(title="Seed", description="Changes which links are drawn."),
        "sample": Props(title="Sample output", description="Name for the new asset of links to check, the link-check task's input."),
    },
)
def kg_sample_links(
    *,
    schema: Input,
    documents: List[Input],
    entity_list: Input,
    groups: List[Input],
    mentions: List[InputDataset],
    relations: List[InputDataset],
    sample: Output,
    links: Optional[List[InputDataset]] = None,
    per_label: int = 50,
    seed: int = 0,
) -> None:
    """Write ``per_label`` links per relation label to ``sample``."""
    if Asset.exists(sample.name):
        raise ValueError(f"An asset named {sample.name} already exists.")
    graph_schema = kg_schema.load(schema.path)
    sources = Sources(
        schema=graph_schema,
        documents=[a.path for a in documents],
        entity_list=entity_list.path,
        groups=[a.path for a in groups],
        mentions=[d.name for d in mentions],
        links=[d.name for d in links or []],
        relations=[d.name for d in relations],
    )
    rows = assemble(sources)
    rows_out = sample_rows(rows, per_label, seed)
    path = sample.local_path(f"{SUBDIR}/{sample.name}.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    n = write_jsonl(path, rows_out)
    sample.register(f"{SUBDIR}/{sample.name}.jsonl", loader="jsonl", version="1.0.0", meta={"rows": n, "per_label": per_label})
    msg = f"Drew {n} links to check from {len(rows.links)} in the graph."
    log(msg)
    print(msg)


def sample_rows(rows, per_label: int, seed: int) -> List[dict]:
    rng = random.Random(seed)
    names = {e["id"]: e["name"] for e in rows.entities}
    passages = {p["passage_id"]: p for p in rows.passages}
    evidence = defaultdict(list)
    for e in rows.evidence:
        evidence[e["link_id"]].append(e)
    by_label_doc = defaultdict(lambda: defaultdict(list))
    for link in rows.links:
        docs = sorted({e["doc_id"] for e in evidence[link["id"]]})
        by_label_doc[link["label"]][docs[0] if docs else ""].append(link)
    out = []
    for label, by_doc in sorted(by_label_doc.items()):
        doc_ids = sorted(by_doc)
        rng.shuffle(doc_ids)
        taken = 0
        for doc_id in doc_ids:
            for link in by_doc[doc_id]:
                if taken >= per_label:
                    break
                lines = [f"{names.get(link['head'], link['head'])}  {label}  {names.get(link['tail'], link['tail'])}", ""]
                for e in evidence[link["id"]]:
                    p = passages.get(e["passage_id"])
                    if p:
                        where = " ".join(x for x in (e["doc_id"], f"v{e['doc_version']}" if e["doc_version"] else "", e["doc_date"]) if x)
                        lines.append(f"[{where}]")
                        lines.append(p["text"])
                        lines.append("")
                out.append(
                    {
                        "text": "\n".join(lines).strip(),
                        "meta": {"link_id": link["id"], "label": label, "group": link["group"], "head_id": link["head"], "tail_id": link["tail"], "doc_id": doc_id, "evidence": link["evidence"]},
                    }
                )
                taken += 1
            if taken >= per_label:
                break
    return out

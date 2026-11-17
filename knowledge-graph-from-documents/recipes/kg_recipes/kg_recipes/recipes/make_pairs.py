"""Action recipe that writes one row per candidate pair of a relation group, for its task.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

from pathlib import Path
from typing import List, Literal, Optional

import prodigy.recipes.textcat
from prodigy.structured_types import TextcatChoiceExample
from prodigy.util import log, set_hashes

from ellf_recipes_sdk import Asset, Dataset, Input, InputDataset, OptionalProps, Output, Props, TextProps, action_recipe, save_examples

from .. import gold as kg_gold
from .. import linking
from .. import pairs as kg_pairs
from .. import schema as kg_schema
from ..data import read_assets, read_datasets, read_jsonl, write_jsonl
from ..documents import documents_by_id, passages_by_id
from ..mentions import mentions_from_answers

SUBDIR = "kg_recipes"


@action_recipe(
    title="Make relation pairs (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Write one row per pair of entities a relation group allows, in a passage or a whole "
        "document, with both ends marked and the conditions found by rule: the relation task's input."
    ),
    category="data",
    field_props={
        "documents": Props(title="Documents", description="The Documents assets."),
        "mentions": OptionalProps(
            title="Mentions", optional_title="Use settled mentions", description="Datasets of settled mentions, as given to Find link candidates."
        ),
        "groups": OptionalProps(
            title="Mention groups", optional_title="Use mention groups", description="The mention groups assets Find link candidates wrote."
        ),
        "links": OptionalProps(
            title="Settled links",
            optional_title="Use settled link answers",
            description="Datasets of settled yes/no link answers. Groups the rule didn't link and nobody has answered are left out.",
        ),
        "gold": OptionalProps(
            title="Gold labels",
            optional_title="Use gold mentions and links (for evaluation)",
            description="A gold labels asset. Its mentions and links replace the datasets', so relations are scored without linking errors.",
        ),
        "gold_relations": OptionalProps(
            title="Gold relations dataset",
            optional_title="Save gold relation answers",
            description="With gold labels: where each pair's gold label is saved as an answer, e.g. relations-gold.",
        ),
        "entity_list": Props(title="Entity list", description="The entity list, for the entries' names."),
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "relation": TextProps(title="Relation group", description="The name of the relation group in the schema."),
        "pairs": Props(title="Pairs output", description="Name for the new asset of pairs, the relation task's input."),
    },
)
def kg_make_pairs(
    *,
    documents: List[Input],
    entity_list: Input,
    schema: Input,
    relation: str,
    pairs: Output,
    mentions: Optional[List[InputDataset]] = None,
    groups: Optional[List[Input]] = None,
    links: Optional[List[InputDataset]] = None,
    gold: Optional[Input] = None,
    gold_relations: Optional[Dataset[Literal["textcat"]]] = None,
) -> None:
    """Write the candidate pairs of ``relation`` to ``pairs``."""
    if Asset.exists(pairs.name):
        raise ValueError(f"An asset named {pairs.name} already exists.")
    graph = kg_schema.load(schema.path)
    group = graph.relation(relation)
    rows = read_assets([a.path for a in documents])
    by_doc = documents_by_id(rows)
    by_passage = passages_by_id(rows)
    names = {r["id"]: r["name"] for r in read_jsonl(Path(entity_list.path))}
    if gold is None and (not mentions or not groups):
        raise ValueError("Give the settled mentions and the mention groups, or gold labels.")
    group_rows = read_assets([a.path for a in groups or []])
    if gold is not None:
        gold_mentions = kg_gold.gold_mentions(read_jsonl(Path(gold.path)), by_doc, graph)
        found = [g.mention for g in gold_mentions]
        nodes = kg_pairs.gold_nodes(gold_mentions, graph, names)
        resolved = {g["group_id"]: ([], "gold") for g in group_rows}
    else:
        found = [m for m in mentions_from_answers(read_datasets([d.name for d in mentions or []])) if m.passage_id in by_passage]
        link_answers = read_datasets([d.name for d in links or []])
        resolved = linking.resolve(group_rows, link_answers)
        nodes = kg_pairs.mention_nodes(found, group_rows, resolved, graph, names, linking.mention_answers(link_answers))
    out = kg_pairs.pair_rows(group, by_doc, found, nodes)
    path = pairs.local_path(f"{SUBDIR}/{pairs.name}.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    n = write_jsonl(path, out)
    pairs.register(f"{SUBDIR}/{pairs.name}.jsonl", loader="jsonl", version="1.0.0", meta={"rows": n, "relation": relation})
    if gold is not None and gold_relations is not None:
        labels = kg_gold.gold_relations(read_jsonl(Path(gold.path)), by_doc, graph)
        stands_for = kg_pairs.gold_ids_of_text_nodes(gold_mentions, graph)
        stream = prodigy.recipes.textcat.add_label_options((set_hashes(dict(r)) for r in out), group.all_labels)
        answers, covered = [], set()
        for row in stream:
            m = row["meta"]
            where = m["doc_id"] if group.scope == "document" else m["passage_id"]
            found = set()
            for h in stands_for.get(m["head_id"]) or {m["head_id"]}:
                for t in stands_for.get(m["tail_id"]) or {m["tail_id"]}:
                    key = kg_gold.relation_key(group.name, where, h, t, group.directed)
                    if key in labels:
                        found |= labels[key]
                        covered.add(key)
            accept = sorted(found) or [kg_schema.NONE]
            answers.append({**row, "accept": accept, "answer": "accept", "_annotator_id": "gold", "_session_id": "gold"})
        save_examples(gold_relations.name, answers, session_id="gold", parse_as=TextcatChoiceExample, view_id="choice")
        # Gold relations with no pair can't be labelled by anyone: an entity dropped as NIL,
        # a mention the gold labels don't have, or a passage-scope relation with no passage.
        total = sum(1 for k in labels if k[0] == group.name)
        no_passage = sum(
            1
            for r in read_jsonl(Path(gold.path))
            for rel in r.get("relations") or []
            if group.scope == "passage" and rel.get("passage") is None and graph.relation_for_label(rel["label"]) is group
        )
        msg = f"Saved {len(answers)} gold relation answers to '{gold_relations.name}'. {len(covered)} of the {total} gold {relation} relations are among the pairs."
        if no_passage:
            msg += f" {no_passage} gold {relation} relations have no passage, which a passage-scope group needs, and were left out."
        log(msg)
        print(msg)
    undecided = sum(1 for g in group_rows if g["group_id"] not in resolved)
    msg = f"Wrote {n} {relation} pairs. {undecided} mention groups aren't linked yet and were left out."
    log(msg)
    print(msg)


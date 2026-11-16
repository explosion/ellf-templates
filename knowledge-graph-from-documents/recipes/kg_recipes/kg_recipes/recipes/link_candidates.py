"""Action recipe that finds each mention's candidate entries, links what the rule can, and
writes yes/no questions for the rest.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

from collections import Counter
from pathlib import Path
from typing import List, Literal, Optional

from prodigy.structured_types import TextcatExample
from prodigy.util import log

from ellf_recipes_sdk import (
    Asset,
    BoolProps,
    Dataset,
    Input,
    InputDataset,
    IntProps,
    OptionalProps,
    Output,
    Props,
    Secret,
    TextProps,
    action_recipe,
    save_examples,
)

from .. import gold as kg_gold
from .. import linking
from .. import llm as kg_llm
from .. import schema as kg_schema
from ..data import read_assets, read_datasets, read_jsonl, write_jsonl
from ..documents import documents_by_id, passages_by_id
from ..mentions import mentions_from_answers

SUBDIR = "kg_recipes"


@action_recipe(
    title="Find link candidates (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Look up each mention's candidate entries in the entity list, link the ones a single "
        "exact match decides, and write one yes/no question per mention and candidate for the rest."
    ),
    category="data",
    field_props={
        "documents": Props(title="Documents", description="The Documents assets the mentions are in."),
        "mentions": Props(
            title="Mentions",
            description="Datasets of settled mentions: the mentions review's, or a gold dataset. Accepted answers only.",
        ),
        "entity_list": Props(title="Entity list", description="A JSONL asset: id, type, name, aliases, description per entry."),
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "broader": BoolProps(
            title="Add broader entries",
            description="For mentions no name matches exactly, also offer the broader entries of the candidates found, from the list's 'broader' field.",
        ),
        "llm_api_key": OptionalProps(
            title="LLM API key",
            optional_title="Add names an LLM proposes",
            description=(
                "For mentions no name matches exactly, an LLM proposes names the entry could be listed under, "
                "and those are looked up too. The mention, its type and the text around it are sent to the provider."
            ),
        ),
        "llm_model": TextProps(title="LLM model", description="The model that proposes names."),
        "llm_url": TextProps(title="LLM API URL", description="Any OpenAI-compatible chat completions endpoint. The default is Gemini's."),
        "context": IntProps(
            title="Context per question",
            description="Characters of text shown on each side of the mention, after the candidate. 0 shows the whole passage.",
            min=0,
        ),
        "questions": Props(title="Questions output", description="Name for the new asset of yes/no questions, the links task's input."),
        "gold": OptionalProps(
            title="Gold labels",
            optional_title="Save gold link answers",
            description="A gold labels asset. With a gold links dataset, its links are saved there as answers to every group's candidates.",
        ),
        "gold_links": OptionalProps(
            title="Gold links dataset",
            optional_title="Save gold link answers",
            description="Where the gold yes/no answers go, e.g. links-gold.",
        ),
        "groups": Props(
            title="Mention groups output",
            description="Name for the new asset of mention groups: their mentions, candidates and the rule's links.",
        ),
    },
)
def kg_link_candidates(
    *,
    documents: List[Input],
    mentions: List[InputDataset],
    entity_list: Input,
    schema: Input,
    questions: Output,
    groups: Output,
    gold: Optional[Input] = None,
    gold_links: Optional[Dataset[Literal["textcat"]]] = None,
    broader: bool = False,
    llm_api_key: Optional[Secret] = None,
    llm_model: str = kg_llm.DEFAULT_MODEL,
    llm_url: str = kg_llm.DEFAULT_URL,
    context: int = linking.CONTEXT,
) -> None:
    """Write the mention groups to ``groups`` and the questions to ``questions``."""
    taken = [o.name for o in (questions, groups) if Asset.exists(o.name)]
    if taken:
        raise ValueError(f"Assets with these names already exist: {', '.join(taken)}.")
    graph = kg_schema.load(schema.path)
    rows = read_assets([a.path for a in documents])
    by_passage = passages_by_id(rows)
    doc_texts = {doc_id: "\n\n".join(p["text"] for p in ps) for doc_id, ps in documents_by_id(rows).items()}
    found = [m for m in mentions_from_answers(read_datasets([d.name for d in mentions])) if m.passage_id in by_passage]
    entities = linking.EntityList.from_rows(read_jsonl(Path(entity_list.path)), graph)
    version = f"{entity_list.name} {entity_list.version}"
    mention_groups = linking.mention_groups(found, graph, doc_texts)
    llm = kg_llm.LLM(llm_api_key.value(), llm_model, llm_url) if llm_api_key is not None else None
    propose = None
    if llm is not None:
        propose = kg_llm.proposer(llm, lambda g, context, n: linking.proposal_prompt(g, graph.entity_types[g.type], context, n))
    contexts = {g.group_id: linking.context_of(g, by_passage) for g in mention_groups} if propose else None
    linking.add_candidates(mention_groups, entities, graph, propose=propose, broader=broader, contexts=contexts)
    question_rows = linking.question_rows(mention_groups, entities, by_passage, version, context=context)
    group_rows = linking.group_rows(mention_groups, version)
    for output, out_rows in ((questions, question_rows), (groups, group_rows)):
        path = output.local_path(f"{SUBDIR}/{output.name}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        n = write_jsonl(path, out_rows)
        output.register(f"{SUBDIR}/{output.name}.jsonl", loader="jsonl", version="1.0.0", meta={"rows": n})
    if gold is not None and gold_links is not None:
        gold_mentions = kg_gold.gold_mentions(read_jsonl(Path(gold.path)), documents_by_id(rows), graph)
        lookup = kg_gold.ids_by_overlap(gold_mentions)
        ids, per_mention = {}, {}
        for g in mention_groups:
            hits = [lookup(m.key) for m in g.mentions]
            ids[g.group_id] = set().union(*[set(x) for x in hits if x is not None])
            for m, x in zip(g.mentions, hits):
                if x is not None:
                    per_mention[(m.passage_id, m.start, m.end)] = set(x)
        answers = linking.gold_answers(mention_groups, ids, mention_ids=per_mention)
        save_examples(gold_links.name, answers, session_id="gold", parse_as=TextcatExample, view_id="classification")
        print(f"Saved {len(answers)} gold link answers to '{gold_links.name}'.")
    decided = Counter("rule" if g["rule_ids"] else ("nil" if g["rule_ids"] == [] else "ask") for g in group_rows)
    msg = (
        f"{len(found)} mentions in {len(group_rows)} groups: {decided['rule']} linked by rule, "
        f"{decided['nil']} with no candidate (NIL), {decided['ask']} to ask about in "
        f"{len(question_rows)} yes/no questions."
    )
    sources = Counter(c.match for g in mention_groups for c in g.candidates)
    msg += " Candidates by source: " + ", ".join(f"{k} {v}" for k, v in sorted(sources.items())) + "."
    if llm is not None:
        msg += f" LLM: {llm.summary()}."
    log(msg)
    print(msg)

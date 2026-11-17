"""Action recipe that asks again where the settled link answers leave a mention group unresolved.

Two cases, both as the same yes/no questions the links task asks, so the same task recipe,
agents and review handle them:

- every candidate of a group was rejected: a wider search, with the optional sources
  (names an LLM proposes, broader entries), without the candidates already asked about;
- a group was linked to more than one entry, but its type links a mention to one (the same
  name meant two things in one document): one question per mention and entry.

Run it after the links review. Its answers go to their own datasets, and every later step
reads both: answers about one mention override its group's.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

from pathlib import Path
from typing import List, Optional

from prodigy.util import log

from ellf_recipes_sdk import (
    Asset,
    BoolProps,
    Input,
    InputDataset,
    IntProps,
    OptionalProps,
    Output,
    Props,
    Secret,
    TextProps,
    action_recipe,
)

from .. import linking
from .. import llm as kg_llm
from .. import schema as kg_schema
from ..data import read_assets, read_datasets, read_jsonl, write_jsonl
from ..documents import passages_by_id

SUBDIR = "kg_recipes"


@action_recipe(
    title="Fix links (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "After the links review: new yes/no questions for mention groups whose every candidate was "
        "rejected (a wider search) and for names linked to two entries (one question per mention)."
    ),
    category="data",
    field_props={
        "documents": Props(title="Documents", description="The Documents assets the mentions are in."),
        "groups": Props(title="Mention groups", description="The mention groups asset Find link candidates wrote."),
        "links": Props(title="Settled links", description="The links review's dataset, and earlier fix-links reviews' if any."),
        "entity_list": Props(title="Entity list", description="The same entity list Find link candidates used."),
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "questions": Props(title="Questions output", description="Name for the new asset of yes/no questions."),
        "wider": IntProps(title="Candidates per group", description="How many candidates the wider search offers.", min=1),
        "context": IntProps(
            title="Context per question",
            description="Characters of text shown on each side of the mention, after the candidate. 0 shows the whole passage.",
            min=0,
        ),
        "broader": BoolProps(title="Add broader entries", description="Also offer the broader entries of the candidates found."),
        "llm_api_key": OptionalProps(
            title="LLM API key",
            optional_title="Add names an LLM proposes",
            description="An LLM proposes names the entry could be listed under. The mention, its type and the text around it are sent to the provider.",
        ),
        "llm_model": TextProps(title="LLM model", description="Your provider's name for the model that proposes names."),
        "llm_url": TextProps(title="LLM API URL", description="Your provider's OpenAI-compatible chat completions endpoint."),
    },
)
def kg_fix_links(
    *,
    documents: List[Input],
    groups: List[Input],
    links: List[InputDataset],
    entity_list: Input,
    schema: Input,
    questions: Output,
    wider: int = 15,
    broader: bool = False,
    llm_api_key: Optional[Secret] = None,
    llm_model: str = "",
    llm_url: str = "",
    context: int = linking.CONTEXT,
) -> None:
    """Write the new questions to ``questions``."""
    if Asset.exists(questions.name):
        raise ValueError(f"An asset named {questions.name} already exists.")
    graph = kg_schema.load(schema.path)
    by_passage = passages_by_id(read_assets([a.path for a in documents]))
    group_rows = read_assets([a.path for a in groups])
    entities = linking.EntityList.from_rows(read_jsonl(Path(entity_list.path)), graph)
    llm = kg_llm.from_settings(llm_api_key.value() if llm_api_key is not None else None, llm_model, llm_url)
    propose = None
    if llm is not None:
        propose = kg_llm.proposer(llm, lambda g, context, n: linking.proposal_prompt(g, graph.entity_types[g.type], context, n))
    rows, counts = linking.fix_rows(
        group_rows,
        read_datasets([d.name for d in links]),
        entities,
        graph,
        by_passage,
        wider=wider,
        propose=propose,
        broader=broader,
        list_version=f"{entity_list.name} {entity_list.version}",
        context=context,
    )
    path = questions.local_path(f"{SUBDIR}/{questions.name}.jsonl")
    n = write_jsonl(path, rows)
    questions.register(f"{SUBDIR}/{questions.name}.jsonl", loader="jsonl", version="1.0.0", meta={"rows": n, **counts})
    msg = (
        f"Wrote {n} questions: {counts['retry']} groups whose candidates were all rejected get a wider search "
        f"({counts['unchanged']} more found nothing new and stay NIL), and {counts['split']} names linked to "
        "more than one entry are asked about mention by mention."
    )
    if llm is not None:
        msg += f" LLM: {llm.summary()}."
    log(msg)
    print(msg)

"""Service recipe that serves the knowledge graph: a page for project members and an API.

The service starts Neo4j inside its own pod, builds the graph from the schema, the
documents and the settled datasets, runs the schema's checks, and serves the questions,
views of any entity and link with the evidence behind it, read-only Cypher, an export,
and optionally questions in plain language. Restart it to pick up new answers; create it
again for new documents or datasets, since a service's arguments are fixed.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

import json
from pathlib import Path
from typing import List, Optional

from ellf_recipes_sdk import Input, InputDataset, OptionalProps, Props, Secret, TextProps, service_recipe

from .. import schema as kg_schema
from ..app import create_app, parse_questions
from ..llm import DEFAULT_MODEL, DEFAULT_URL, LLM
from ..graph import Sources

PORT = 8000


@service_recipe(
    title="Knowledge Graph",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Serve a Neo4j graph of your documents' entities and relations, with the evidence behind "
        "every link: a page for project members and an API. Rebuilt from your assets and datasets on every start."
    ),
    port=PORT,
    healthcheck_path="/health",
    auth="session",
    category="dashboard",
    field_props={
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "questions": Props(title="Questions", description="The questions asset: config/questions.json, published."),
        "documents": Props(title="Documents", description="Every Documents asset, evaluation ones included."),
        "entity_list": Props(title="Entity list", description="The entity list the mentions are linked to."),
        "groups": Props(title="Mention groups", description="Every mention groups asset Find link candidates wrote."),
        "mentions": Props(title="Settled mentions", description="The mentions review's dataset, and gold mentions if you have them."),
        "links": OptionalProps(
            title="Settled links", optional_title="Use settled link answers", description="The links review's dataset."
        ),
        "relations": Props(title="Settled relations", description="The relation reviews' datasets."),
        "relations_labelled": OptionalProps(
            title="Relation answers",
            optional_title="Show every labeller's answer",
            description="The relation tasks' datasets, shown beside each piece of evidence.",
        ),
        "scores": OptionalProps(
            title="Scores",
            optional_title="Show precision and recall",
            description="The scores file scripts/score.py writes, published as an asset.",
        ),
        "llm_api_key": OptionalProps(
            title="LLM API key",
            optional_title="Answer questions in plain language",
            description="Stored as an Ellf secret. A plain-language question and the schema are sent to the provider to write a query.",
        ),
        "llm_model": TextProps(title="LLM model", description="The model that writes queries."),
        "llm_url": TextProps(title="LLM API URL", description="Any OpenAI-compatible chat completions endpoint. The default is Gemini's."),
    },
)
def kg_graph(
    *,
    schema: Input,
    questions: Input,
    documents: List[Input],
    entity_list: Input,
    groups: List[Input],
    mentions: List[InputDataset],
    relations: List[InputDataset],
    links: Optional[List[InputDataset]] = None,
    relations_labelled: Optional[List[InputDataset]] = None,
    scores: Optional[Input] = None,
    llm_api_key: Optional[Secret] = None,
    llm_model: str = DEFAULT_MODEL,
    llm_url: str = DEFAULT_URL,
):
    """Build the graph and serve it. Returns the web app, which the SDK serves on ``PORT``."""
    graph_schema = kg_schema.load(schema.path)
    sources = Sources(
        schema=graph_schema,
        documents=[a.path for a in documents],
        entity_list=entity_list.path,
        groups=[a.path for a in groups],
        mentions=[d.name for d in mentions],
        links=[d.name for d in links or []],
        relations=[d.name for d in relations],
        relations_labelled=[d.name for d in relations_labelled or []],
        list_version=f"{entity_list.name} {entity_list.version}",
    )
    names = {
        "documents": ", ".join(f"{a.name} {a.version}" for a in documents),
        "entity list": f"{entity_list.name} {entity_list.version}",
        "mentions": ", ".join(d.name for d in mentions),
        "links": ", ".join(d.name for d in links or []) or "rule only",
        "relations": ", ".join(d.name for d in relations),
    }
    figures = json.loads(Path(scores.path).read_text(encoding="utf-8")) if scores is not None else None
    llm = LLM(llm_api_key.value(), llm_model, llm_url) if llm_api_key is not None else None
    asked = parse_questions(Path(questions.path).read_text(encoding="utf-8"))
    return create_app(sources, asked, names, figures, llm)

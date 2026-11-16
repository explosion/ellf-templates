"""Action recipe that saves the mentions found by rules or a pretrained model as labellers.

The examples are built the way the mentions task (``kg_mentions``) builds them over the same Documents
asset, so their hashes match the task's: review, the consensus and the scores treat each
method like any other labeller, under its own annotator name. Unless ``overlapping`` is on,
as in the task, overlapping pattern matches keep only the longest, which the task's compact
view can hold.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

import json
from typing import Dict, Literal, Optional

import prodigy.recipes.spans
import spacy
from prodigy.structured_types import SpansManualExample
from prodigy.util import log

from ellf_recipes_sdk import (
    BoolProps,
    Dataset,
    Input,
    Model,
    OptionalProps,
    Patterns,
    Props,
    TextProps,
    action_recipe,
    save_examples,
)

from .. import schema as kg_schema
from ..mentions import as_answer, label_tasks, model_spans


@action_recipe(
    title="Find mentions by rule or model (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Save the mentions that spaCy patterns or a pretrained spaCy pipeline find in the "
        "documents to the mentions task's dataset, each method as its own labeller, so they're "
        "scored like the others."
    ),
    category="data",
    field_props={
        "documents": Props(title="Documents", description="The Documents asset the mentions task reads."),
        "dataset": Props(title="Mentions dataset", description="The mentions task's dataset."),
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "patterns": OptionalProps(
            title="Patterns",
            optional_title="Find mentions with patterns",
            description="spaCy token or phrase patterns, each labelled with an entity type.",
        ),
        "model": OptionalProps(
            title="spaCy pipeline",
            optional_title="Find mentions with a pretrained pipeline",
            description="A spaCy pipeline asset with an entity recognizer.",
        ),
        "label_map": TextProps(
            title="Model labels to entity types (JSON)",
            description='e.g. {"ORG": "COMPANY"}. Entities whose label maps to no entity type are left out.',
        ),
        "lang": TextProps(title="Language", description="Tokenizer language, the same as the mentions task's."),
        "overlapping": BoolProps(
            title="Mentions can overlap",
            description="The same setting as the mentions task's. Off, overlapping pattern matches keep only the longest.",
        ),
        "tokenizer": OptionalProps(
            title="Tokenizer",
            optional_title="Use the project's tokenizer",
            description="The tokenizer asset Make tokenizer wrote, the same one the mentions task uses.",
        ),
    },
)
def kg_find_mentions(
    *,
    documents: Input,
    dataset: Dataset[Literal["spans"]],
    schema: Input,
    patterns: Optional[Patterns] = None,
    model: Optional[Model] = None,
    label_map: str = "{}",
    lang: str = "en",
    tokenizer: Optional[Model] = None,
    overlapping: bool = False,
) -> None:
    """Save each method's mentions to ``dataset``, as the annotators ``patterns:<asset>`` and ``model:<asset>``."""
    graph = kg_schema.load(schema.path)
    types = list(graph.entity_types)
    if patterns is None and model is None:
        raise ValueError("Choose patterns, a spaCy pipeline, or both.")
    mapping: Dict[str, str] = json.loads(label_map or "{}")
    nlp = tokenizer.load() if tokenizer is not None else spacy.blank(lang)

    def tasks():
        return prodigy.recipes.spans.add_tokens(nlp, documents.load(rehash=True, dedup=True, input_key="text"))

    def save(examples, annotator: str) -> int:
        batch, n = [], 0
        for eg in examples:
            batch.append(eg)
            if len(batch) >= 500:
                save_examples(dataset.name, batch, session_id=annotator, parse_as=SpansManualExample, view_id="spans_manual")
                n += len(batch)
                batch = []
        if batch:
            save_examples(dataset.name, batch, session_id=annotator, parse_as=SpansManualExample, view_id="spans_manual")
            n += len(batch)
        return n

    if patterns is not None:
        annotator = f"patterns:{patterns.name}"
        matcher = patterns.load(nlp=nlp, label=types, allow_overlap=overlapping)

        def matched():
            for _, eg in matcher(documents.load(rehash=True, dedup=True, input_key="text")):
                spans = [{"start": s["start"], "end": s["end"], "label": s["label"]} for s in eg.get("spans") or []]
                yield as_answer({k: v for k, v in eg.items() if k != "spans"}, spans, annotator)

        n = save(prodigy.recipes.spans.add_tokens(nlp, matched()), annotator)
        log(f"Saved {n} passages labelled by {annotator}")
        print(f"Saved {n} passages labelled by {annotator}")
    if model is not None:
        annotator = f"model:{model.name}"
        pipeline = model.load()
        found = label_tasks(tasks(), lambda texts: model_spans(pipeline, texts, mapping, types), annotator)
        n = save(prodigy.recipes.spans.add_tokens(nlp, found), annotator)
        log(f"Saved {n} passages labelled by {annotator}")
        print(f"Saved {n} passages labelled by {annotator}")

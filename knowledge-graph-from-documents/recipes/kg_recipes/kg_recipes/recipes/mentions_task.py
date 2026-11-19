"""Task recipe for marking mentions: the built-in ``spans`` task, with the project's tokenizer.

Mentions that can't overlap (the default) are marked in the compact ``ner_manual`` view;
``overlapping`` switches to ``spans_manual``. Both save the same answers, and agents label
both.

The built-in task tokenizes with a blank pipeline of a language, or with a pipeline that
has a span categorizer; a pipeline with only a tokenizer, like the one Make tokenizer saves,
isn't accepted. This task takes one, so the passages are split the same way here, in
import-gold and in find-mentions, and a mention like ``VCM`` in ``(VCM)-induced`` can be
marked on its own. Answers are saved like the built-in task's, except that an example is
hashed on its passage id as well as its text, so a passage whose text appears elsewhere
too, like a repeated table row, is labelled in each place.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

from typing import Literal, Optional, Union

import prodigy.recipes.spans
import spacy
from prodigy.structured_types import SpansManualExample

from ellf_recipes_sdk import (
    AnnotationSettings,
    BoolProps,
    Dataset,
    Input,
    Labels,
    LabelScheme,
    Model,
    OptionalProps,
    Patterns,
    TextProps,
    props,
    task_recipe,
)

from ..mentions import hashed, passage_tasks, view_id


@task_recipe(
    title="Mentions (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description="Mark the mentions of each entity type, with the project's tokenizer: the built-in spans task, for text that needs its own word splitting.",
    category="text",
    view_id="spans_manual",
    field_props={
        "dataset": props.dataset_choice,
        "input": TextProps(title="Documents", description="The Documents asset to label."),
        "label": props.label_scheme_for("TYPE_A, TYPE_B, ..."),
        "tokenizer": OptionalProps(
            title="Tokenizer",
            optional_title="Use the project's tokenizer",
            description="The tokenizer asset Make tokenizer wrote. Without it, a blank pipeline of the language.",
        ),
        "lang": TextProps(title="Language", description="Used when no tokenizer is given."),
        "overlapping": BoolProps(
            title="Mentions can overlap",
            description="Allow one mention inside another. Off, the passage is shown compactly with labels inline; on, it uses the spans view, which leaves room under every line.",
        ),
        "patterns": OptionalProps(
            title="Patterns",
            optional_title="Suggest mentions with patterns",
            description="spaCy patterns, each labelled with an entity type.",
        ),
    },
    cli_names={"label-list": "label", "label-labels": "label-scheme"},
)
def kg_mentions(
    *,
    dataset: Dataset[Literal["spans"]],
    input: Input[Literal["text"]],
    label: Union[list[str], Labels],
    tokenizer: Optional[Model] = None,
    lang: str = "en",
    overlapping: bool = False,
    patterns: Optional[Patterns] = None,
    settings: AnnotationSettings = AnnotationSettings(),
):
    """Serve the passages for marking mentions."""
    nlp = tokenizer.load() if tokenizer is not None else spacy.blank(lang)
    scheme = LabelScheme.resolve(label)
    labels = scheme.names()
    stream = passage_tasks(input.load(input_key="text"))
    if patterns is not None:
        matcher = patterns.load(nlp=nlp, label=labels, allow_overlap=overlapping)
        # The matcher hashes the examples again, on their text alone.
        stream = (hashed(eg) for _, eg in matcher(stream))
    return {
        "dataset": dataset.name,
        "stream": prodigy.recipes.spans.add_tokens(nlp, stream),
        "view_id": view_id(overlapping),
        "parse_as": SpansManualExample,
        "exclude": settings.exclude_names,
        "config": settings.prodigy_config(labels=labels, label_definitions=scheme.definitions(), lang=nlp.lang),
    }

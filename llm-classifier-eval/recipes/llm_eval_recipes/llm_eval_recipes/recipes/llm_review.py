"""Settle disagreements between an LLM classifier and people.

The annotators' blind labels are reviewed side by side with the LLM's, in
Prodigy's review interface: each text where someone's label differs from the
LLM's, or who chose UNCLEAR, is shown once, with every answer as a version,
and the reviewer's choice is saved as the final label. An annotator's version
is credited to their dataset, so one person's sittings count once and a
second annotator, in a dataset of their own, shows separately.
"""

import copy
from typing import Any, Iterator, Literal, Union, cast

import prodigy.recipes.review
from prodigy.components.db import connect
from prodigy.components.stream import Stream
from prodigy.errors import RecipeError
from prodigy.types import RecipeSettingsType
from prodigy.util import SESSION_ID_ATTR, log

from ellf_recipes_sdk import (
    AnnotationSettings,
    Dataset,
    Input,
    InputDataset,
    ListProps,
    TextProps,
    props,
    task_recipe,
)

LLM_SESSION_ID = "LLM"


@task_recipe(
    title="LLM Disagreement Review",
    description="Settle the texts where people's blind labels differ from an LLM classifier's, with every answer in view, and save one final label per text.",
    view_id="review",
    category="data",
    field_props={
        # fmt: off
        "dataset": props.dataset_choice,
        "annotations": ListProps(
            title="Annotation datasets",
            description="The datasets of the blind text classification tasks whose labels are compared with the LLM's.",
            exists=True,
        ),
        "llm_labels": TextProps(
            title="LLM labels",
            description="Input data with the LLM's label for each text, in meta.reference_label: the same texts the annotators labelled.",
        ),
        "unclear": TextProps(
            title="Unclear label",
            description="The label annotators choose when they could defend more than one answer. Texts labelled with it are always reviewed.",
        ),
        # fmt: on
    },
)
def llm_review(
    *,
    dataset: Dataset[Literal["review"]],
    annotations: list[InputDataset],
    llm_labels: Input[Literal["text"]],
    unclear: str = "UNCLEAR",
    settings: AnnotationSettings = AnnotationSettings(),
) -> RecipeSettingsType:
    """Review the annotators' labels against the LLM's, where they differ.

    Contract:
        Preconditions:
            - ``annotations`` are structured datasets of choice (``textcat``)
              tasks, whose options include the LLM's labels, plus ``unclear``,
              and for one label X, ``NOT_X``.
            - ``llm_labels`` holds the texts exactly as the annotators saw
              them, each with ``meta.reference_label``.

        Raises:
            RecipeError: If an annotation dataset holds examples from before
                structured storage, none of them holds any annotations yet,
                or no annotated text disagrees with the LLM.
            RecipeError: From ``get_review_stream`` if the annotations come
                from different interfaces.
            Database errors from ``connect()`` (not caught).
    """
    log("RECIPE: Starting recipe llm_review", locals())
    db = connect()
    unmigrated = [ds.name for ds in annotations if db.count_legacy_examples(ds.name)]
    if unmigrated:
        raise RecipeError(
            f"Only structured datasets can be reviewed: {', '.join(unmigrated)}",
            "Convert them with the built-in migration action first.",
        )
    # A dataset nothing was saved to yet isn't marked structured: an optional
    # second annotator who hasn't started has nothing to add
    names = [ds.name for ds in annotations if db.get_dataset_by_name(ds.name).structured]
    if not names:
        raise RecipeError(
            "Nothing to review: the annotation datasets are empty",
            "Annotate the texts in the blind task first.",
        )
    llm = {
        eg["text"]: eg["meta"]["reference_label"]
        for eg in llm_labels.load(input_key="text")
        if "reference_label" in (eg.get("meta") or {})
    }
    by_dataset, sources = prodigy.recipes.review.get_structured_review_examples(
        db, names, credit=credit_dataset
    )
    people, machine = select_disagreements(by_dataset, llm, unclear)
    if not machine:
        raise RecipeError(
            "Nothing to review: no annotated text disagrees with the LLM",
            "Check that the LLM labels asset holds the texts the annotators saw.",
        )
    log(f"RECIPE: Reviewing {len(machine)} texts")
    # Annotators first, so on a tie their version is the default one
    stream = prodigy.recipes.review.get_review_stream(
        {**people, LLM_SESSION_ID: machine}
    )
    cast(Stream, stream).apply(
        prodigy.recipes.review.to_structured_review_stream,
        stream=stream,
        sources=sources,
    )
    labels = option_ids(machine[0])
    return {
        "view_id": "review",
        "dataset": dataset.name,
        "stream": stream,
        "config": settings.prodigy_config(labels=labels),
    }


def select_disagreements(
    by_dataset: dict[str, list[dict[str, Any]]],
    llm: dict[str, Union[str, list[str]]],
    unclear: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """The annotators' answers on texts where any of them differs from the
    LLM or chose `unclear`, and the LLM's answer on each of those texts, as a
    copy of an annotator's with the LLM's label accepted.

    by_dataset (dict): Flat answers by dataset, from
        `get_structured_review_examples`.
    llm (dict): The LLM's label by text.
    unclear (str): The label for "more than one answer is defensible".
    RETURNS (tuple): The annotators' answers by dataset, and the LLM's.
    """
    disputed: dict[str, dict[str, Any]] = {}
    for examples in by_dataset.values():
        for eg in accepted(examples):
            if eg["text"] not in llm:
                continue
            ids = option_ids(eg)
            ours = llm_choice(llm[eg["text"]], ids)
            if unclear in eg["accept"] or sorted(eg["accept"]) != ours:
                if eg["text"] not in disputed:
                    machine = copy.deepcopy(eg)
                    machine["accept"] = ours
                    machine[SESSION_ID_ATTR] = LLM_SESSION_ID
                    disputed[eg["text"]] = machine
    people = {
        name: [eg for eg in accepted(examples) if eg["text"] in disputed]
        for name, examples in by_dataset.items()
    }
    return people, list(disputed.values())


def credit_dataset(dataset_name: str, _session_id: str, _extras: dict[str, Any]) -> str:
    """Credit a version to its dataset: one per annotator in this template."""
    return dataset_name


def accepted(examples: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for eg in examples:
        if eg.get("answer") == "accept" and eg.get("options"):
            yield eg


def option_ids(eg: dict[str, Any]) -> list[str]:
    return [str(option["id"]) for option in eg.get("options") or []]


def llm_choice(value: Union[str, list[str], None], ids: list[str]) -> list[str]:
    """The options the LLM's label selects. With one label X the options are
    X, NOT_X and UNCLEAR, and any LLM label other than X means NOT_X."""
    values = value if isinstance(value, list) else [value]
    chosen = sorted(str(v) for v in values if str(v) in ids)
    if chosen:
        return chosen
    negatives = [i for i in ids if i.startswith("NOT_")]
    if len(negatives) == 1:
        return negatives
    return []

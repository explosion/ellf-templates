"""Split a dataset of NER annotations into folds, for jackknifing.

Jackknifing finds annotation errors with models that never saw the texts
they're checked on: each fold's texts are predicted by a model trained on the
other folds, and where the model disagrees with an annotation, the annotation
is worth a second look. This action makes the data for one round of that:

- `<prefix>`: every text's annotation, credited to `gold`. The held-out
  predictions are imported into it beside them, so the built-in review shows
  each text where the model and the annotation disagree, and auto-accepts the
  rest.
- `<prefix>-fold-<k>`: the annotations of fold k, to train the other folds'
  models on.
- `<prefix>-fold-<k>-texts`: fold k's texts with their tokens and no
  entities, for the built-in 'Annotate with spaCy' action to predict.

The annotations are copied as manual NER answers whatever they came from (an
NER task, an import or a review), so every round's review compares the same
kind of example.
"""

import random
from typing import Any, Dict, List, Optional, Tuple

from ellf_recipes_sdk import (
    Asset,
    InputDataset,
    IntProps,
    Output,
    Props,
    TextProps,
    action_recipe,
    props,
    refuse_unmigrated_datasets,
    save_examples,
)

GOLD = "gold"
#: The interfaces whose answers are whole manual annotations of a text. A
#: binary NER answer accepts or rejects one entity, which isn't a gold
#: annotation of the text.
MANUAL_VIEWS = ("ner_manual", "spans_manual", "review")


def fold_names(prefix: str, folds: int) -> Tuple[List[str], List[str]]:
    """The datasets and assets of each fold."""
    datasets = [f"{prefix}-fold-{k}" for k in range(1, folds + 1)]
    return datasets, [f"{name}-texts" for name in datasets]


def recorded_view(eg: Any) -> Optional[str]:
    """The interface a structured example was annotated in, if it records one:
    in its config, as the server stores it, as the interface a review answer
    was given for, or as a plain task's `_view_id`."""
    extras = eg.extras or {}
    return (
        (eg.config or {}).get("view_id")
        or extras.get("view_id")
        or extras.get("_view_id")
    )


def span_key(task: Dict[str, Any]) -> Tuple[Tuple[int, int, str], ...]:
    return tuple(
        sorted((s["start"], s["end"], s.get("label") or "") for s in task["spans"])
    )


def gold_tasks(db: Any, name: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """One accepted manual NER task per text, from a structured dataset, and
    how many examples were left out, by why.

    RAISES (RecipeError): If an example isn't a manual NER annotation or has
        no tokens, or a text has two accepted annotations that differ.
    """
    from prodigy.errors import RecipeError

    by_input: Dict[int, Dict[str, Any]] = {}
    conflicting: set = set()
    left_out = {"rejected": 0, "ignored": 0, "duplicates": 0}
    for _, eg in db.iter_st_dataset_session_examples(name):
        view = recorded_view(eg)
        if view is not None and view not in MANUAL_VIEWS:
            raise RecipeError(
                f"'{name}' has answers from the '{view}' interface",
                "Jackknifing checks whole manual NER annotations, e.g. from the NER task's manual interface or a review of them.",
            )
        task = eg.to_unst()
        answer = task.get("answer")
        if answer != "accept":
            left_out["rejected" if answer == "reject" else "ignored"] += 1
            continue
        if not task.get("tokens"):
            raise RecipeError(
                f"An annotation in '{name}' has no tokens (input hash {task['_input_hash']})",
                "Annotate the texts on their tokens, as the NER task does, or import them with their tokens.",
            )
        task["spans"] = task.get("spans") or []
        h = task["_input_hash"]
        if h in by_input:
            if span_key(by_input[h]) != span_key(task):
                conflicting.add(h)
            left_out["duplicates"] += 1
            continue
        by_input[h] = task
    if conflicting:
        first = sorted(conflicting)[0]
        raise RecipeError(
            f"{len(conflicting)} texts in '{name}' have accepted annotations that differ (first: input hash {first})",
            "Settle them first, e.g. in an Annotation Review task, and split the reviewed dataset.",
        )
    return [by_input[h] for h in sorted(by_input)], left_out


def assign_folds(hashes: List[int], folds: int, seed: int) -> Dict[int, int]:
    """Each input hash's fold, from 1 to `folds`, in folds of equal size give
    or take one. The same texts and seed give the same folds."""
    order = sorted(hashes)
    random.Random(seed).shuffle(order)
    return {h: i % folds + 1 for i, h in enumerate(order)}


def gold_copy(task: Dict[str, Any], fold: int) -> Dict[str, Any]:
    """The annotation as a manual NER answer credited to `gold`, with its fold
    in its meta."""
    return {
        "text": task["text"],
        "tokens": task["tokens"],
        "spans": [
            {
                "start": s["start"],
                "end": s["end"],
                "label": s["label"],
                "token_start": s["token_start"],
                "token_end": s["token_end"],
            }
            for s in task["spans"]
        ],
        "meta": {**(task.get("meta") or {}), "fold": fold},
        "answer": "accept",
        "_input_hash": task["_input_hash"],
        "_annotator_id": GOLD,
        "_view_id": "ner_manual",
    }


@action_recipe(
    title="Split annotations into folds for jackknifing",
    description=(
        "Split manual NER annotations into folds for a round of jackknifing: a dataset per fold to train on, "
        "an asset of each fold's texts to predict, and a copy of every annotation to review the predictions against."
    ),
    category="data",
    field_props={
        "annotations": Props(
            title="Annotations",
            description="A dataset of manual NER annotations, one accepted answer per text, e.g. from the NER task or the last round's review.",
        ),
        "prefix": TextProps(
            title="Name prefix",
            description="The names of the datasets and assets this round makes start with it, e.g. jk-r1. They must not exist yet.",
            placeholder="jk-r1",
            validations=props.asset_name_validations,
        ),
        "folds": IntProps(
            title="Folds",
            description="How many folds, and so models, to make. Each model trains on the other folds' texts.",
            min=2,
            max=20,
        ),
        "seed": IntProps(
            title="Random seed",
            description="The same annotations and seed give the same folds.",
            min=0,
        ),
    },
)
def jackknife_folds(
    *, annotations: InputDataset, prefix: str, folds: int = 4, seed: int = 0
) -> None:
    """Split the annotations into folds and save each fold's training data,
    its texts to predict, and a copy of every annotation to compare with.

    Contract:
        Raises:
            RecipeError: Before writing anything, if the prefix is empty,
                there are fewer than two folds or fewer texts than folds, an
                output dataset already has examples or an output asset
                exists, or the annotations aren't one accepted manual NER
                answer per text with tokens (see `gold_tasks`).
    """
    from prodigy.components.db import connect
    from prodigy.errors import RecipeError
    from prodigy.structured_types import SpansManualExample
    from prodigy.util import msg

    prefix = prefix.strip()
    if not prefix:
        raise RecipeError("Name the prefix for this round's datasets and assets.")
    if folds < 2:
        raise RecipeError(f"Jackknifing needs at least two folds, not {folds}.")
    datasets, assets = fold_names(prefix, folds)
    db = connect()
    if annotations.name in [prefix, *datasets]:
        raise RecipeError(
            f"'{annotations.name}' is the dataset to split, so it can't be an output too.",
            "Choose another prefix.",
        )
    refuse_unmigrated_datasets(db, [annotations.name, prefix, *datasets])
    taken = [n for n in [prefix, *datasets] if n in db and db.count_st_dataset(n)]
    taken += [n for n in assets if Asset.exists(n)]
    if taken:
        raise RecipeError(
            f"These already exist: {', '.join(taken)}",
            "Choose a new prefix for each round.",
        )
    tasks, left_out = gold_tasks(db, annotations.name)
    if len(tasks) < folds:
        raise RecipeError(
            f"'{annotations.name}' has {len(tasks)} accepted annotations, fewer than the {folds} folds."
        )
    fold_of = assign_folds([t["_input_hash"] for t in tasks], folds, seed)
    copies = [gold_copy(t, fold_of[t["_input_hash"]]) for t in tasks]
    save_examples(
        prefix,
        copies,
        session_id=GOLD,
        parse_as=SpansManualExample,
        view_id="ner_manual",
    )
    for k, (dataset, asset) in enumerate(zip(datasets, assets), start=1):
        fold = [eg for eg in copies if eg["meta"]["fold"] == k]
        save_examples(
            dataset,
            [dict(eg) for eg in fold],
            session_id=GOLD,
            parse_as=SpansManualExample,
            view_id="ner_manual",
        )
        Output(name=asset).write_jsonl(
            (
                {
                    "text": eg["text"],
                    "tokens": eg["tokens"],
                    "meta": eg["meta"],
                    "_input_hash": eg["_input_hash"],
                }
                for eg in fold
            ),
            meta={"annotations": annotations.name, "fold": k, "folds": folds},
        )
        others = ",".join(d for d in datasets if d != dataset)
        msg.text(
            f"Fold {k}: {len(fold)} texts in '{dataset}' and '{asset}'; its model trains on {others}"
        )
    skipped = ", ".join(f"{n} {why}" for why, n in left_out.items() if n)
    msg.good(
        f"Split {len(tasks)} annotations from '{annotations.name}' into {folds} folds, "
        f"with a copy of each in '{prefix}'" + (f" (left out: {skipped})" if skipped else "")
    )

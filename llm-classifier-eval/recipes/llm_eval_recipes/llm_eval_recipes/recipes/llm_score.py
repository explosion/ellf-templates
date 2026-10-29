"""Score an LLM classifier against people's labels on the cluster.

Reads the blind annotations, and optionally the adjudication and a second
annotator, straight from their datasets, and prints the LLM's accuracy and
per-label precision, recall and true rates, weighted back to all of its
traffic, to the action's log. It can score other predictions on the same texts
instead, e.g. a revised prompt's, and save the gold set as an asset.
"""

from typing import Literal, Optional

from prodigy.util import log

from ellf_recipes_sdk import (
    BoolProps,
    Input,
    InputDataset,
    IntProps,
    OptionalProps,
    Output,
    Props,
    TextProps,
    action_recipe,
)

from .. import evaluation


@action_recipe(
    title="Score an LLM Classifier",
    description="Measure an LLM classifier against people's blind labels: accuracy and per-label precision, recall and true rates across all of its traffic, with confidence intervals, in the action's log.",
    category="data",
    field_props={
        # fmt: off
        "annotations": Props(
            title="Annotations",
            description="The dataset of the blind text classification task over the sample.",
        ),
        "sample": TextProps(
            title="Sample with the LLM's labels",
            description="The LLM's label, stratum and weight for each sampled record, as written by the llm_eval_sample action.",
        ),
        "adjudication": OptionalProps(
            title="Adjudication",
            optional_title="Use the settled labels",
            description="The dataset of the adjudication task: its labels overrule the annotations.",
        ),
        "second": OptionalProps(
            title="Second annotator",
            optional_title="Measure agreement with a second annotator",
            description="The dataset of the second annotator's blind task, for Cohen's kappa between the two.",
        ),
        "predictions": OptionalProps(
            title="Other predictions",
            optional_title="Score other predictions instead of the LLM's",
            description="Input data with a label for each sampled text in meta.reference_label, e.g. from a revised prompt.",
        ),
        "gold": OptionalProps(
            title="Gold set",
            optional_title="Save the gold set",
            description="A new input asset for the settled texts, with the gold label, the LLM's label and the weight in meta.",
        ),
        "labels_exclusive": BoolProps(
            title="Mutually exclusive labels",
            description="Every text has exactly one correct label.",
        ),
        "unclear": TextProps(
            title="Unclear label",
            description="The label annotators choose when they could defend more than one answer.",
        ),
        "show": IntProps(
            title="Example texts per mistake",
            description="How many texts to print for each of the most common mistakes.",
            min=0,
        ),
        "bootstrap": IntProps(
            title="Bootstrap samples",
            description="Resamples for the 95% intervals. 0 leaves the intervals out.",
            min=0,
        ),
        # fmt: on
    },
)
def llm_eval_score(
    *,
    annotations: InputDataset,
    sample: Input[Literal["text"]],
    adjudication: Optional[InputDataset] = None,
    second: Optional[InputDataset] = None,
    predictions: Optional[Input[Literal["text"]]] = None,
    gold: Optional[Output] = None,
    labels_exclusive: bool = True,
    unclear: str = "UNCLEAR",
    show: int = 5,
    bootstrap: int = 1000,
) -> None:
    """Print the score report, and save the gold set if asked.

    Contract:
        Preconditions:
            - ``annotations`` (and ``adjudication``, ``second``) are
              structured text classification datasets over the sampled texts.
            - ``sample`` rows carry ``meta.stratum`` and ``meta.weight``.

        Raises:
            ValueError: If ``sample`` has no stratum or weight, or the
                annotations have no label options.
            Database errors from ``InputDataset.load()`` (not caught).
    """
    log("RECIPE: Starting recipe llm_eval_score", locals())
    rows = list(annotations.load())
    ids = evaluation.option_ids(rows)
    if not ids:
        raise ValueError(f"No annotated text classification examples in '{annotations.name}'.")
    scheme = evaluation.scheme_from_options(ids, unclear, labels_exclusive)
    answers = evaluation.read_answers(rows, scheme, unclear)
    settled = (
        evaluation.read_answers(adjudication.load(), scheme, unclear) if adjudication else None
    )
    gold_labels = evaluation.gold_labels(answers, settled)
    sampled = evaluation.read_sampled(sample.load(input_key="text"))
    others = None
    if predictions is not None:
        others = {
            evaluation.text_id(eg["text"]): scheme.key((eg.get("meta") or {}).get("reference_label"))
            for eg in predictions.load(input_key="text")
        }
    lines = evaluation.score_report(
        sampled,
        gold_labels,
        scheme,
        unclear=unclear,
        predictions=others,
        show=show,
        n_bootstrap=bootstrap,
    )
    if second is not None:
        lines += ["", f"Agreement between '{annotations.name}' and '{second.name}':"]
        second_answers = evaluation.read_answers(second.load(), scheme, unclear)
        lines += evaluation.agreement_report(answers, second_answers)
    print("\n".join(lines))
    if gold is not None:
        n = gold.write_jsonl(evaluation.gold_rows(sampled, gold_labels, unclear))
        print(f"\nSaved {n} gold texts to the asset '{gold.name}'")

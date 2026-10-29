"""Draw the evaluation sample from an LLM classifier's past decisions.

The records are sampled separately within each label the LLM gave, so rare
labels can be measured, and each sampled record carries the weight that brings
it back to its share of all records. The annotation tasks load the blind
sample, which holds only the texts; the LLM's labels and the weights go to a
separate asset that only the adjudication and the scoring read.
"""

from typing import Literal

from prodigy.util import log

from ellf_recipes_sdk import (
    BoolProps,
    Input,
    IntProps,
    Labels,
    Output,
    Props,
    TextProps,
    action_recipe,
)

from .. import evaluation


@action_recipe(
    title="Sample an LLM Classifier's Decisions",
    description="Draw a stratified random sample of an LLM classifier's past decisions to annotate blind, weighted back to all of its traffic.",
    category="data",
    field_props={
        # fmt: off
        "records": TextProps(
            title="LLM decisions",
            description="Input data with the LLM's past decisions: the text it saw, and its raw label in meta.reference_label.",
        ),
        "label_scheme": Props(
            title="Annotation labels",
            description="The labels annotators choose from: the classifier's labels plus UNCLEAR, and for one label X, X, NOT_X and UNCLEAR.",
        ),
        "blind": Props(
            title="Blind sample",
            description="New input asset with each sampled text once and no labels, for the annotation task.",
        ),
        "pilot": Props(
            title="Pilot sample",
            description="New input asset with a random subset of the blind sample, for the pilot.",
        ),
        "second": Props(
            title="Second-annotator sample",
            description="New input asset with a random subset of the blind sample, for a second annotator.",
        ),
        "sample": Props(
            title="Sample with the LLM's labels",
            description="New input asset with every sampled record, its LLM label and its weight, for the adjudication and the scoring. Annotators never load it.",
        ),
        "size": IntProps(
            title="Sample size",
            description="Records to sample in all, shared between the LLM's labels by how often it gives each.",
            min=1,
        ),
        "min_per_label": IntProps(
            title="Minimum per label",
            description="Records to sample at least for each label the LLM gives, so rare labels can be measured.",
            min=1,
        ),
        "pilot_size": IntProps(
            title="Pilot size",
            description="Texts in the pilot sample.",
            min=0,
        ),
        "second_size": IntProps(
            title="Second-annotator sample size",
            description="Texts in the second annotator's sample.",
            min=0,
        ),
        "labels_exclusive": BoolProps(
            title="Mutually exclusive labels",
            description="Every text has exactly one correct label.",
        ),
        "unclear": TextProps(
            title="Unclear label",
            description="The annotation label for texts where more than one answer is defensible.",
        ),
        "seed": IntProps(
            title="Random seed",
            description="The same seed and records give the same sample.",
            min=0,
        ),
        # fmt: on
    },
)
def llm_eval_sample(
    *,
    records: Input[Literal["text"]],
    label_scheme: Labels,
    blind: Output,
    pilot: Output,
    second: Output,
    sample: Output,
    size: int = 300,
    min_per_label: int = 20,
    pilot_size: int = 50,
    second_size: int = 50,
    labels_exclusive: bool = True,
    unclear: str = "UNCLEAR",
    seed: int = 0,
) -> None:
    """Sample the records and write the four sample assets.

    Contract:
        Preconditions:
            - ``records`` rows have a ``text`` and ``meta.reference_label``;
              rows without them are skipped and counted.
            - ``label_scheme`` holds the annotation labels, so the LLM's
              labels can be told apart from UNCLEAR and, for one label X,
              mapped to X or NOT_X.

        Raises:
            ValueError: If no record has a text and a reference label, or
                the label scheme isn't valid (from ``Labels.load()``).
            Errors from ``Output.write_jsonl`` if an output asset's name is
                already taken (not caught).
    """
    log("RECIPE: Starting recipe llm_eval_sample", locals())
    names = label_scheme.load().names()
    scheme = evaluation.scheme_from_options(names, unclear, labels_exclusive)
    drawn = evaluation.draw_sample(
        records.load(),
        scheme,
        size=size,
        min_per_label=min_per_label,
        pilot=pilot_size,
        second=second_size,
        seed=seed,
    )
    n_records = sum(n for n, _, _ in drawn.strata.values())
    print(f"Records: {n_records}")
    if drawn.skipped:
        print(f"Skipped {drawn.skipped} records without a text or meta.reference_label")
    print("LLM label: records, sampled, weight")
    for stratum, (n, k, weight) in drawn.strata.items():
        print(f"  {stratum}: {n}, {k}, {weight:.2f}")
    for output, rows in [
        (blind, drawn.blind),
        (pilot, drawn.pilot),
        (second, drawn.second),
        (sample, drawn.sampled),
    ]:
        written = output.write_jsonl(rows)
        print(f"Wrote {written} rows to the asset '{output.name}'")

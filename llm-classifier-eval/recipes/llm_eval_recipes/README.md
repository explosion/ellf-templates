# llm_eval_recipes

The custom recipe the [llm-classifier-eval](../../README.md) template adjudicates with.

## `llm_review`

A task that settles the texts where people's blind labels differ from an LLM
classifier's. It reads the annotation datasets of the blind `textcat` tasks and an
input asset with the LLM's label for each text (`meta.reference_label`), and serves
every text where an annotator and the LLM disagree, or an annotator chose UNCLEAR,
in Prodigy's review interface. Each answer is a version credited to where it came
from: `LLM`, or the annotator's dataset, so one person's sittings count once and a
second annotator in a dataset of their own shows separately. The reviewer's choice
is saved to the task's dataset as a text classification example.

```bash
ellf tasks create llm_review --name "eval-adjudicate" --dataset "eval_adjudication" --annotations "eval_annotations" --annotations "eval_second" --llm-labels "eval-llm-labels" --no-start
```

With one label `X`, the annotation options are `X`, `NOT_X` and UNCLEAR, and any LLM
label other than `X` counts as `NOT_X`. The texts to review are chosen when the task
starts, so start it once the annotation is done.

## Publishing

```bash
ellf publish code recipes/llm_eval_recipes
```

The version comes from `llm_eval_recipes/about.py`: bump it there for each change.

## Tests

The tests need Prodigy and `ellf-recipes-sdk` installed, plus the dev requirements:

```bash
pip install -e . -r requirements-dev.in
pytest tests
```

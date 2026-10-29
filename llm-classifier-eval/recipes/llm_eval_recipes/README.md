# llm_eval_recipes

The custom recipes of the [llm-classifier-eval](../../README.md) template: two actions
and a task that measure an LLM classifier against people.

## `llm_eval_sample` (action)

Draws the evaluation sample from an input asset of the LLM's past decisions (text,
and the LLM's raw label in `meta.reference_label`). The decisions are sampled
separately within each label the LLM gave, with a minimum per label, and each
sampled record carries the weight that brings it back to its share of all the
decisions. It writes four input assets: the blind sample (texts only), a pilot and a
second-annotator subset of it, and the sample with the LLM's labels, stratum and
weight in `meta`.

## `llm_review` (task)

Settles the texts where people's blind labels differ from the LLM's. It reads the
annotation datasets and the sample with the LLM's labels, and serves every text
where an annotator and the LLM disagree, or an annotator chose UNCLEAR, in Prodigy's
review interface. Each answer is a version credited to `LLM` or to the annotator's
dataset, so one person's sittings count once and a second annotator in a dataset of
their own shows separately.

## `llm_eval_score` (action)

Scores the LLM against the settled labels, read straight from the datasets, and
prints the report to its log: accuracy, per-label precision, recall and F1, and each
label's rate as the LLM gives it against its estimated true rate, weighted to all of
the decisions, with stratified bootstrap intervals. Optionally it adds agreement with
a second annotator, scores other predictions on the same texts instead of the LLM's
(e.g. a revised prompt's), and saves the gold set as an asset.

With one label `X`, the annotation labels are `X`, `NOT_X` and UNCLEAR, and any LLM
label other than `X` counts as `NOT_X`.

## Publishing

```bash
ellf publish code recipes/llm_eval_recipes
```

The version comes from `llm_eval_recipes/about.py`: bump it there for each change.

## Tests

The sampling and scoring logic is in `llm_eval_recipes/evaluation.py`, standard
library only. The tests need Prodigy and `ellf-recipes-sdk` installed, plus the dev
requirements:

```bash
pip install -e . -r requirements-dev.in
pytest tests
```

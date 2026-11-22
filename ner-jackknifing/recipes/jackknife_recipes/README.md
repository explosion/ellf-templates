# jackknife_recipes

The custom action of the [ner-jackknifing](../../README.md) template.

## `jackknife_folds`

Splits a dataset of manual NER annotations into folds, for one round of jackknifing.
Every text lands in exactly one fold, in folds of equal size give or take one; the
same annotations and `--seed` give the same folds. With `--prefix jk-r1` and
`--folds 4`, it makes:

| Name | What | Read by |
|---|---|---|
| `jk-r1-fold-1` … `jk-r1-fold-4` | datasets: each fold's annotations | the built-in `train`: fold k's model trains on the other folds |
| `jk-r1-fold-1-texts` … `jk-r1-fold-4-texts` | input assets: each fold's texts with their tokens and no entities | the built-in `spacy_annotate`, with fold k's model |
| `jk-r1` | dataset: every annotation, credited to `gold` | the built-in `import_annotations` adds the predictions beside them; the built-in `review` compares the two |

The annotations are copied as manual NER answers whatever they came from: an NER
task, an import, or the previous round's review. So every round's review compares
the same kind of example, and its auto-accept recognises a text where the model
agrees with the annotation as one version with two annotators. Each text's fold is
in its `meta.fold`, which the review shows.

```bash
ellf actions create jackknife_folds --name "Folds r1" --annotations "pii_gold" --prefix jk-r1 --folds 4 --no-start
```

It refuses before writing anything if:

- an output dataset already has examples, or an output asset exists: choose a new
  prefix each round;
- a text has two accepted annotations that differ: settle them first, e.g. in a
  review task;
- an answer comes from the binary `ner` interface, or has no tokens.

Rejected and ignored answers are left out and counted in the log. Errors name input
hashes, never texts, as the texts may hold personal data.

## Publishing

```bash
ellf publish code recipes/jackknife_recipes
```

The version comes from `jackknife_recipes/about.py`: bump it there for each change.

## Tests

The tests need Prodigy and `ellf-recipes-sdk` installed, plus the dev requirements.
The test of a whole round also needs `ellf-recipes`, for the built-in review and import,
and is skipped without it.

```bash
pip install -e . -r requirements-dev.in
pytest tests
```

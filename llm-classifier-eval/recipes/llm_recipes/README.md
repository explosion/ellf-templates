# llm_recipes

The custom action of the [llm-classifier-eval](../../README.md) template.

## `llm_to_dataset`

Saves your LLM classifier's answers on an input asset of texts to a dataset, credited
to their own session (`LLM` by default). The answers are saved the way the built-in
text classification task saves a person's for the same labels: one label is an
accept or reject question, several are a choice. So the built-in review shows the
LLM's answer and a person's on the same text as versions of one example, and the
annotation dashboard compares them like two annotators.

The answers come from one of two places:

- **Logged decisions** (`--llm-label-key reference_label`): the LLM's label is in
  each record's `meta`. With one label X, any other value means X doesn't apply.
- **`classify`**: called once per text, it returns the labels the LLM gives it, or
  `None` for no usable answer. The default sends your instructions, the label
  definitions and the text to an OpenAI-compatible chat endpoint and reads label
  names from the reply. Change it to match your production classifier: its prompt,
  API and parsing.

Options:

- **`--sample-size`, `--min-per-label`**: draw a sample separately within each label
  the LLM gave, each with its share and at least the minimum, and record each
  answer's weight in `meta.weight`: the number of texts with its label over the
  number sampled.
- **`--blind`, `--blind.name`**: write the texts, in random order and without the LLM's
  labels, to a new input asset for the annotation tasks.

```bash
ellf actions create llm_to_dataset --name "eval-llm" --input "eval-records" --label-scheme "classifier-labels" --labels-exclusive --output "eval_llm" --llm-label-key "reference_label" --sample-size 300 --blind --blind.name "eval-blind" --no-start
```

Each distinct text counts once. Texts with no usable answer are left out and counted
in the log. A failed request stops the action, so a bad key or model fails before it
has run through the texts.

## Publishing

```bash
ellf publish code recipes/llm_recipes
```

The version comes from `llm_recipes/about.py`: bump it there for each change.

## Tests

The tests need Prodigy and `ellf-recipes-sdk` installed, plus the dev requirements:

```bash
pip install -e . -r requirements-dev.in
pytest tests
```

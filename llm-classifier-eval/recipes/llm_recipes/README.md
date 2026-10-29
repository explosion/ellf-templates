# llm_recipes

The custom action of the [llm-classifier-eval](../../README.md) template.

## `llm_to_dataset`

Runs your LLM classifier over an input asset of texts and saves its answers to a
dataset, credited to their own session (`LLM` by default). The answers are saved the
way the built-in text classification task saves a person's for the same labels: one
label is an accept or reject question, several are a choice. So the built-in review
shows the LLM's answer and a person's on the same text as versions of one example,
and the annotation dashboard compares them like two annotators.

```bash
ellf actions create llm_to_dataset --name "eval-llm" --input "eval-texts" --label-scheme "classifier-labels" --labels-exclusive --output "eval_llm" --api-key LLM_API_KEY --model "<your model>" --instructions "<your prompt>" --no-start
```

### Customising it

`classify` in `llm_recipes/recipes/llm_to_dataset.py` is called once per text and
returns the labels the LLM gives it, or `None` for no usable answer. The default sends
your instructions, the label definitions and the text to an OpenAI-compatible chat
endpoint and reads label names from the reply. Change it to match your production
classifier: its prompt, API and parsing. If the decisions are already logged, put them
in each text's `meta` and return them from there.

Texts with no usable answer are left out and counted in the action's log. A failed
request stops the action, so a bad key or model fails before it has run through the
texts.

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

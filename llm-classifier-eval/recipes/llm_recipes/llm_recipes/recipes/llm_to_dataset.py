"""Save an LLM classifier's answers on texts as annotations.

The answers are saved the way the built-in text classification task saves a
person's, credited to their own session, so the LLM becomes one more
annotator: the built-in review compares it with people, and the annotation
dashboard shows where they agree.

The answers come from one of two places: the LLM's labels already in each
record's meta, e.g. logged production decisions, or `classify`, which calls
the LLM. Customise `classify` to match your LLM: its prompt, the API it calls
and how its reply is read.

Optionally, the action draws a sample separately within each label the LLM
gave, so rare labels can be measured, records each sampled answer's weight
(texts with its label over sampled texts with its label) in its meta, and
writes the sampled texts without the LLM's labels for people to annotate.
"""

import random
from collections import defaultdict
from typing import Any, Iterable, Literal, Optional, Union, cast

import httpx
import prodigy.recipes.textcat
from prodigy.structured_types import TextcatChoiceExample, TextcatExample

from ellf_recipes_sdk import (
    BoolProps,
    Dataset,
    Input,
    IntProps,
    Labels,
    LabelScheme,
    OptionalProps,
    Output,
    Props,
    Secret,
    TextProps,
    action_recipe,
    props,
    save_examples,
)


def classify(
    eg: dict[str, Any],
    scheme: LabelScheme,
    exclusive: bool,
    *,
    client: httpx.Client,
    model: str,
    instructions: str,
) -> Optional[list[str]]:
    """The labels the LLM gives a text, or None if it gave no usable answer.

    Customise this to match your LLM. The default asks an OpenAI-compatible
    chat endpoint to reply with label names. If the decisions are logged,
    return them instead, e.g. `return [eg["meta"]["llm_label"]]`.

    eg (dict): The example, with the text in `eg["text"]` and any meta.
    scheme (LabelScheme): The labels, with their definitions.
    exclusive (bool): Whether exactly one label applies.
    RETURNS (Optional[list[str]]): The labels that apply, from `scheme`.
    """
    definitions = "\n".join(
        f"- {spec.name}: {spec.description}" if spec.description else f"- {spec.name}"
        for spec in scheme.labels
    )
    task = "the one label" if exclusive else "every label"
    prompt = (
        f"{instructions}\n\nLabels:\n{definitions}\n\n"
        f"Reply with {task} that applies to the text, by name, separated by "
        f"commas, and nothing else. Reply NONE if none applies.\n\nText:\n{eg['text']}"
    )
    response = client.post(
        "/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
    )
    response.raise_for_status()
    reply = response.json()["choices"][0]["message"]["content"].strip()
    if reply.upper() == "NONE":
        return []
    names = set(scheme.names())
    chosen = [part.strip() for part in reply.split(",") if part.strip() in names]
    if not chosen or (exclusive and len(chosen) > 1):
        return None
    return chosen


def logged_labels(eg: dict[str, Any], key: str, names: list[str]) -> Optional[list[str]]:
    """The labels the LLM gave, from `eg["meta"][key]`: a label or a list of
    them. With one label X, any other value means X doesn't apply. None if the
    record has none, or none from the scheme."""
    value = (eg.get("meta") or {}).get(key)
    if value is None:
        return None
    values = [str(v) for v in (value if isinstance(value, list) else [value])]
    if len(names) == 1:
        return names if names[0] in values else []
    chosen = [v for v in values if v in names]
    return chosen or None


def stratum(chosen: list[str], names: list[str]) -> str:
    if len(names) == 1:
        return names[0] if chosen else f"NOT_{names[0]}"
    return "+".join(sorted(chosen)) or "NONE"


def draw_sample(
    answered: list[tuple[dict[str, Any], list[str]]],
    names: list[str],
    *,
    size: int,
    min_per_label: int,
    seed: int,
) -> list[tuple[dict[str, Any], list[str], float]]:
    """A sample drawn separately within each label the LLM gave: each gets its
    share of `size`, and at least `min_per_label`. Each sampled answer's
    weight is the number of texts with its label over the number sampled."""
    rng = random.Random(seed)
    strata: defaultdict[str, list[tuple[dict[str, Any], list[str]]]] = defaultdict(list)
    for eg, chosen in answered:
        strata[stratum(chosen, names)].append((eg, chosen))
    total = len(answered)
    sampled = []
    print("LLM label: texts, sampled, weight")
    for key in sorted(strata, key=lambda k: -len(strata[k])):
        group = strata[key]
        n = min(len(group), max(min_per_label, round(size * len(group) / total)))
        weight = len(group) / n
        sampled.extend((eg, chosen, weight) for eg, chosen in rng.sample(group, n))
        print(f"  {key}: {len(group)}, {n}, {weight:.2f}")
    rng.shuffle(sampled)
    return sampled


@action_recipe(
    title="Label Texts with Your LLM",
    description="Save your LLM classifier's answers on texts to a dataset as another annotator's, to compare with people's in the built-in review and annotation dashboard. Takes logged LLM labels or calls the LLM, and can draw a sample by the LLM's label.",
    category="data",
    field_props={
        # fmt: off
        "input": TextProps(
            title="Input data",
            description="The texts, as people annotate them, optionally with the LLM's label in their meta.",
        ),
        "label": props.label_scheme_for("BILLING, TECHNICAL, ..."),
        "output": Props(
            title="Output dataset",
            description="Dataset to save the LLM's answers to.",
        ),
        "labels_exclusive": BoolProps(
            title="Mutually exclusive labels",
            description="Every text has exactly one correct label. Use the same setting as the annotation task.",
        ),
        "llm_label_key": TextProps(
            title="Logged LLM label",
            optional_title="Read the LLM's labels from the input",
            description="The meta key that holds the LLM's label, e.g. reference_label. Without it, the action calls the LLM.",
        ),
        "sample_size": IntProps(
            title="Sample size",
            optional_title="Draw a sample by the LLM's label",
            description="Texts to sample in all, shared between the LLM's labels by how often it gives each, with each answer's weight in its meta.",
            min=1,
        ),
        "min_per_label": IntProps(
            title="Minimum per label",
            description="When sampling, texts to take at least for each label the LLM gives, so rare labels can be measured.",
            min=1,
        ),
        "blind": OptionalProps(
            title="Texts to annotate",
            optional_title="Save the texts without the LLM's labels",
            description="A new input asset with the texts in random order and the LLM's label removed, for the annotation tasks.",
        ),
        "seed": IntProps(
            title="Random seed",
            description="The same seed and input give the same sample and order.",
            min=0,
        ),
        "api_key": OptionalProps(
            title="API key",
            optional_title="Use an API key",
            description="The LLM provider's API key, stored as an Ellf secret.",
        ),
        "model": TextProps(
            title="Model",
            description="The model name the endpoint expects.",
        ),
        "base_url": TextProps(
            title="API base URL",
            description="An OpenAI-compatible endpoint, e.g. https://api.openai.com/v1.",
        ),
        "instructions": TextProps(
            title="Instructions",
            description="What the LLM is told about the task: your production prompt, without its output format.",
        ),
        "session": TextProps(
            title="Annotator name",
            description="Who the answers are credited to in the review and the dashboard.",
        ),
        # fmt: on
    },
    cli_names={"label-list": "label", "label-labels": "label-scheme"},
)
def llm_to_dataset(
    *,
    input: Input[Literal["text"]],
    label: Union[list[str], Labels],
    output: Dataset[Literal["textcat"]],
    labels_exclusive: bool = False,
    llm_label_key: Optional[str] = None,
    sample_size: Optional[int] = None,
    min_per_label: int = 20,
    blind: Optional[Output] = None,
    seed: int = 0,
    api_key: Optional[Secret] = None,
    model: str = "gpt-4o-mini",
    base_url: str = "https://api.openai.com/v1",
    instructions: str = "",
    session: str = "LLM",
) -> None:
    """Save the LLM's answer on every text, or on a sample, to ``output``.

    The examples are built as the built-in text classification task builds
    them for the same labels, so the LLM's answer and a person's on the same
    text are versions of one example in the review: one label is an accept or
    reject question, several are a choice. Each distinct text counts once.

    Contract:
        Raises:
            ValueError: If there are no labels, or no text has a usable
                answer.
            httpx errors from ``classify`` (not caught): a failed request
                stops the action, so a bad key or model fails fast.
            Database errors from ``save_examples()``, and errors from
                ``Output.write_jsonl`` if the asset name is taken (not caught).
    """
    scheme = LabelScheme.resolve(label)
    names = scheme.names()
    if not names:
        raise ValueError("No labels to classify with.")
    binary = len(names) == 1
    exclusive = labels_exclusive or binary
    rows = list(cast(Iterable[dict[str, Any]], input.load(rehash=True, dedup=True, input_key="text")))
    answered: list[tuple[dict[str, Any], list[str]]] = []
    unusable = 0
    headers = {"Authorization": f"Bearer {api_key.value()}"} if api_key is not None else {}
    with httpx.Client(base_url=base_url, headers=headers, timeout=60) as client:
        for eg in rows:
            if llm_label_key:
                chosen = logged_labels(eg, llm_label_key, names)
            else:
                chosen = classify(
                    eg,
                    scheme,
                    exclusive,
                    client=client,
                    model=model,
                    instructions=instructions.strip(),
                )
            if chosen is None:
                unusable += 1
                continue
            answered.append((eg, chosen))
    if not answered:
        raise ValueError("No text has a usable answer from the LLM.")
    if unusable:
        print(f"{unusable} of {len(rows)} texts have no usable answer and are left out")
    if sample_size:
        picked = draw_sample(answered, names, size=sample_size, min_per_label=min_per_label, seed=seed)
    else:
        picked = [(eg, chosen, None) for eg, chosen in answered]
        random.Random(seed).shuffle(picked)
    # Before the examples are built: building adds to the same dicts
    hidden = {llm_label_key} if llm_label_key else set()
    unlabelled = [
        {
            "text": eg["text"],
            "meta": {k: v for k, v in (eg.get("meta") or {}).items() if k not in hidden},
        }
        for eg, _, _ in picked
    ]
    texts = [eg for eg, _, _ in picked]
    if binary:
        built = list(prodigy.recipes.textcat.add_labels_to_stream(texts, names))
    else:
        built = list(prodigy.recipes.textcat.add_label_options(texts, names))
    examples = []
    for eg, (_, chosen, weight) in zip(built, picked):
        if binary:
            eg["answer"] = "accept" if chosen else "reject"
        else:
            eg["accept"] = chosen
            eg["answer"] = "accept"
        if weight is not None:
            eg["meta"] = {**(eg.get("meta") or {}), "weight": weight}
        examples.append(eg)
    save_examples(
        output.name,
        examples,
        session_id=session,
        parse_as=TextcatExample if binary else TextcatChoiceExample,
        view_id="classification" if binary else "choice",
    )
    print(f"Saved {len(examples)} of the LLM's answers to '{output.name}'")
    if blind is not None:
        n = blind.write_jsonl(unlabelled)
        print(f"Wrote {n} texts to annotate, without the LLM's labels, to '{blind.name}'")
    elif llm_label_key:
        print(
            f"The input holds the LLM's labels in meta.{llm_label_key}: annotate the "
            "texts from a blind asset, not the input, or annotators will see them."
        )

"""Run an LLM classifier over texts and save its answers as annotations.

The answers are saved the way the built-in text classification task saves a
person's, credited to their own session, so the LLM becomes one more
annotator: the built-in review compares it with people, and the annotation
dashboard shows where they agree.

Customise `classify` to match your LLM: its prompt, the API it calls and how
its reply is read. If your LLM's decisions are already logged, it can read
them from each example's meta instead of calling anything.
"""

from typing import Any, Iterable, Literal, Optional, Union, cast

import httpx
import prodigy.recipes.textcat
from prodigy.structured_types import TextcatChoiceExample, TextcatExample

from ellf_recipes_sdk import (
    BoolProps,
    Dataset,
    Input,
    Labels,
    LabelScheme,
    OptionalProps,
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


@action_recipe(
    title="Label Texts with Your LLM",
    description="Run your LLM classifier over texts and save its answers to a dataset as another annotator's, to compare with people's in the built-in review and annotation dashboard.",
    category="data",
    field_props={
        # fmt: off
        "input": TextProps(
            title="Input data",
            description="The texts to classify: the same input people annotate.",
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
    api_key: Optional[Secret] = None,
    model: str = "gpt-4o-mini",
    base_url: str = "https://api.openai.com/v1",
    instructions: str = "",
    session: str = "LLM",
) -> None:
    """Classify every text and save the answers to ``output``.

    The examples are built as the built-in text classification task builds
    them for the same labels, so the LLM's answer and a person's on the same
    text are versions of one example in the review: one label is an accept or
    reject question, several are a choice.

    Contract:
        Raises:
            ValueError: If there are no labels.
            httpx errors from ``classify`` (not caught): a failed request
                stops the action, so a bad key or model fails fast.
            Database errors from ``save_examples()`` (not caught).
    """
    scheme = LabelScheme.resolve(label)
    names = scheme.names()
    if not names:
        raise ValueError("No labels to classify with.")
    binary = len(names) == 1
    stream = input.load(rehash=True, dedup=True, input_key="text")
    if binary:
        stream = prodigy.recipes.textcat.add_labels_to_stream(stream, names)
    else:
        stream = prodigy.recipes.textcat.add_label_options(stream, names)
    headers = {"Authorization": f"Bearer {api_key.value()}"} if api_key is not None else {}
    examples = []
    unusable = 0
    with httpx.Client(base_url=base_url, headers=headers, timeout=60) as client:
        for eg in cast(Iterable[dict[str, Any]], stream):
            chosen = classify(
                eg,
                scheme,
                labels_exclusive or binary,
                client=client,
                model=model,
                instructions=instructions.strip(),
            )
            if chosen is None:
                unusable += 1
                continue
            if binary:
                eg["answer"] = "accept" if chosen else "reject"
            else:
                eg["accept"] = chosen
                eg["answer"] = "accept"
            examples.append(eg)
    save_examples(
        output.name,
        examples,
        session_id=session,
        parse_as=TextcatExample if binary else TextcatChoiceExample,
        view_id="classification" if binary else "choice",
    )
    print(f"Saved {len(examples)} of the LLM's answers to '{output.name}'")
    if unusable:
        print(f"{unusable} texts got no usable answer and were left out")

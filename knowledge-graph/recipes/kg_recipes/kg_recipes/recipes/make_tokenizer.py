"""Action recipe that builds the project's tokenizer: a blank spaCy pipeline that also splits
words at characters you choose, saved as a model asset.

spaCy's tokenizer keeps ``(VCM)-induced`` together after the opening bracket, so ``VCM`` can't
be marked on its own, and a gold span that ends inside it has to be widened, which changes the
text entity linking looks up. Splitting at brackets, slashes, plus signs and hyphens fixes both.
The mentions task, import-gold and find-mentions all take the same tokenizer, so their
examples and offsets match.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

import re

import spacy
from prodigy.util import log
from spacy.util import compile_infix_regex, compile_prefix_regex, compile_suffix_regex

from ellf_recipes_sdk import Model, Output, Props, TextProps, action_recipe

SUBDIR = "kg_recipes/tokenizers"
DEFAULT_SPLIT = "( ) [ ] / + -"


def build(lang: str, split: str) -> "spacy.language.Language":
    """A blank pipeline whose tokenizer also splits before and after every character in ``split``."""
    nlp = spacy.blank(lang)
    chars = [re.escape(c) for c in split.split() if c]
    if chars:
        defaults = nlp.Defaults
        nlp.tokenizer.prefix_search = compile_prefix_regex(list(defaults.prefixes or []) + chars).search
        nlp.tokenizer.suffix_search = compile_suffix_regex(list(defaults.suffixes or []) + chars).search
        nlp.tokenizer.infix_finditer = compile_infix_regex(list(defaults.infixes or []) + chars).finditer
    nlp.meta["name"] = "kg_tokenizer"
    nlp.meta["description"] = f"Blank {lang} pipeline that also splits at: {split}"
    return nlp


@action_recipe(
    title="Make tokenizer (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Save a blank spaCy pipeline whose tokenizer also splits at characters you choose, such as "
        "brackets and hyphens, as a model asset for the mentions task, import-gold and find-mentions."
    ),
    category="data",
    field_props={
        "lang": TextProps(title="Language", description="The spaCy language code of your documents."),
        "split": TextProps(
            title="Also split at",
            description="Characters to split words at, separated by spaces.",
            placeholder=DEFAULT_SPLIT,
        ),
        "tokenizer": Props(title="Tokenizer output", description="Name for the new model asset."),
    },
)
def kg_make_tokenizer(*, tokenizer: Output, lang: str = "en", split: str = DEFAULT_SPLIT) -> None:
    """Build the tokenizer and register it as the model asset ``tokenizer``."""
    if Model.exists(tokenizer.name):
        raise ValueError(f"A model named {tokenizer.name} already exists.")
    nlp = build(lang, split)
    subpath = f"{SUBDIR}/{tokenizer.name}"
    nlp.to_disk(tokenizer.local_path(subpath))
    Model.create(name=tokenizer.name, path="{__data__}/" + subpath, version="1.0.0", meta={"format": "directory", "lang": lang, "split": split})
    sample = "(VCM)-induced TGF-beta/Smad3 and CHX+Pilo [3H]SCH"
    msg = f"Saved the tokenizer '{tokenizer.name}'. {sample!r} becomes: " + " | ".join(t.text for t in nlp(sample))
    log(msg)
    print(msg)

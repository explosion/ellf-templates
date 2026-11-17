"""Action recipe that loads gold labels that come with the documents.

The gold mentions go to the mentions gold dataset, built the way the mentions task builds
its examples, so the scores and the gold swap compare them with every labeller. Gold links
and relations stay in the gold asset, which the scores and the graph read directly.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

from pathlib import Path
from typing import List, Literal, Optional

import prodigy.recipes.spans
import spacy
from prodigy.structured_types import SpansManualExample
from prodigy.util import log, set_hashes

from ellf_recipes_sdk import BoolProps, Dataset, Input, Model, OptionalProps, Props, TextProps, action_recipe, save_examples

from .. import gold as kg_gold
from .. import schema as kg_schema
from ..data import read_assets, read_jsonl
from ..documents import documents_by_id, is_whole_document, passages_by_id
from ..mentions import token_aligned, view_id


@action_recipe(
    title="Import gold labels (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Load gold mentions, links and relations that come with the documents: the mentions "
        "go to the mentions gold dataset, built like the mentions task's examples."
    ),
    category="data",
    field_props={
        "gold": Props(title="Gold labels", description="A JSONL asset in the template's gold format, one row per document."),
        "documents": Props(title="Documents", description="The Documents assets the gold labels refer to, usually the evaluation documents."),
        "dataset": Props(title="Mentions gold dataset", description="Where the gold mentions are saved."),
        "schema": Props(title="Graph schema", description="The graph schema asset: config/graph_schema.json, published."),
        "lang": TextProps(title="Language", description="Tokenizer language, the same as the mentions task's."),
        "annotator": TextProps(title="Annotator name", description="Who the gold labels are credited to."),
        "tokenizer": OptionalProps(
            title="Tokenizer",
            optional_title="Use the project's tokenizer",
            description="The tokenizer asset Make tokenizer wrote, the same one the mentions task uses.",
        ),
        "overlapping": BoolProps(
            title="Mentions can overlap",
            description="The same setting as the mentions task's, so the gold mentions are saved in its view.",
        ),
    },
)
def kg_import_gold(
    *,
    gold: Input,
    documents: List[Input],
    dataset: Dataset[Literal["spans"]],
    schema: Input,
    lang: str = "en",
    annotator: str = "gold",
    tokenizer: Optional[Model] = None,
    overlapping: bool = False,
) -> None:
    """Save the gold mentions of the given documents to ``dataset``."""
    graph = kg_schema.load(schema.path)
    rows = read_assets([a.path for a in documents])
    by_doc = documents_by_id(rows)
    by_passage = passages_by_id(rows)
    gold_rows = list(read_jsonl(Path(gold.path)))
    mentions = kg_gold.gold_mentions(gold_rows, by_doc, graph)
    gold_docs = [r["doc_id"] for r in gold_rows if r.get("doc_id") in by_doc]
    # Every passage of a gold document is gold, those with no mentions too, except the
    # whole-document passages, which aren't labelled for mentions.
    passage_ids = [p["meta"]["passage_id"] for d in gold_docs for p in by_doc[d] if not is_whole_document(p)]
    examples = kg_gold.spans_examples(mentions, by_passage, passage_ids)
    # Hashed like the mentions task's examples: on the passage text alone, before the spans.
    nlp = tokenizer.load() if tokenizer is not None else spacy.blank(lang)
    hashed, widened, dropped = [], 0, 0
    for eg in examples:
        task = set_hashes({"text": eg["text"], "meta": eg["meta"]}, overwrite=True)
        spans, w, d = token_aligned(nlp, eg["text"], eg["spans"])
        widened, dropped = widened + w, dropped + d
        hashed.append({**task, "spans": spans, "answer": "accept", "_annotator_id": annotator, "_session_id": annotator})
    tokenized = list(prodigy.recipes.spans.add_tokens(nlp, hashed))
    save_examples(dataset.name, tokenized, session_id=annotator, parse_as=SpansManualExample, view_id=view_id(overlapping))
    missing = len({r["doc_id"] for r in gold_rows} - set(by_doc))
    msg = (
        f"Saved {len(mentions)} gold mentions in {len(tokenized)} passages to '{dataset.name}' "
        f"({sum(1 for eg in tokenized if not eg.get('spans'))} of them with none). "
        f"{widened} spans that ended inside a token were widened to whole tokens, {dropped} that covered "
        f"no token were left out, and {missing} gold documents aren't in the given Documents assets."
    )
    log(msg)
    print(msg)

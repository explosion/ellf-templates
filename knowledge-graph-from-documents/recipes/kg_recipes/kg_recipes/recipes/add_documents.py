"""Action recipe that turns documents into the Documents asset every other step reads.

Don't use ``from __future__ import annotations`` in this module. The recipe schema
builder reads the parameter annotations with ``inspect.signature`` and expects the
actual classes, like ``Input``, not strings.
"""

from pathlib import Path
from typing import List, Optional

from prodigy.util import log

from ellf_recipes_sdk import Asset, BoolProps, FloatProps, Input, OptionalProps, Output, Props, TextProps, action_recipe

from .. import documents as docs
from ..data import read_assets, read_jsonl, write_jsonl

SUBDIR = "kg_recipes"


@action_recipe(
    title="Add documents (knowledge graph)",
    # Recipe descriptions are limited to 255 characters.
    description=(
        "Turn documents into one row per passage for the knowledge graph tasks, and set whole "
        "documents aside for evaluation, by document and before anything is labelled. Writes new assets."
    ),
    category="data",
    field_props={
        "source": Props(
            title="Documents",
            description="A JSONL asset with one document per line: doc_id, and passages or text. See the template's README.",
        ),
        "documents": Props(title="Documents output", description="Name for the new asset of passages to label."),
        "eval_documents": OptionalProps(
            title="Evaluation documents output",
            optional_title="Set evaluation documents aside",
            description="Name for a new asset of the evaluation documents' passages, kept out of labelling.",
        ),
        "eval_share": FloatProps(
            title="Share of documents for evaluation",
            description="Chosen by a hash of each document's id, so adding documents later never moves earlier ones.",
            min=0.0,
            max=1.0,
        ),
        "whole_document": BoolProps(
            title="Add a whole-document passage",
            description="Also write each document's whole text as one passage, for relations stated across a document.",
        ),
        "earlier": OptionalProps(
            title="Earlier batches",
            optional_title="Skip documents from earlier batches",
            description="Documents assets of earlier runs, evaluation ones included. Documents already in them, same id and version, are skipped.",
        ),
        "seed": TextProps(title="Evaluation seed", description="Changes which documents are chosen. Keep it the same across batches."),
    },
)
def kg_add_documents(
    *,
    source: Input,
    documents: Output,
    eval_documents: Optional[Output] = None,
    eval_share: float = 0.2,
    whole_document: bool = False,
    earlier: Optional[List[Input]] = None,
    seed: str = "eval",
) -> None:
    """Write the passages of new documents to ``documents``, and the evaluation documents' to ``eval_documents``."""
    outputs = [o for o in (documents, eval_documents) if o is not None]
    taken = [o.name for o in outputs if Asset.exists(o.name)]
    if taken:
        raise ValueError(f"Assets with these names already exist: {', '.join(taken)}. Name the new batch differently.")
    known = docs.known_documents(read_assets([a.path for a in earlier or []]))
    parsed, problems, skipped = [], [], 0
    for i, row in enumerate(read_jsonl(Path(source.path))):
        try:
            doc = docs.parse_document(row, whole_document=whole_document)
        except ValueError as err:
            problems.append(f"line {i + 1}: {err}")
            continue
        if (doc.doc_id, doc.version) in known:
            skipped += 1
            continue
        parsed.append(doc)
    if problems:
        shown = "\n".join(problems[:20])
        raise ValueError(f"{len(problems)} documents can't be used:\n{shown}")
    if eval_documents is not None:
        to_label, held = docs.split(parsed, eval_share, seed)
    else:
        to_label, held = parsed, []
    written = {}
    for output, chosen in ((documents, to_label), (eval_documents, held)):
        if output is None:
            continue
        path = output.local_path(f"{SUBDIR}/{output.name}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        n = write_jsonl(path, (row for doc in chosen for row in docs.passage_rows(doc)))
        output.register(f"{SUBDIR}/{output.name}.jsonl", loader="jsonl", version="1.0.0", meta={"rows": n, "documents": len(chosen)})
        written[output.name] = (len(chosen), n)
    summary = "; ".join(f"{name}: {d} documents, {n} passages" for name, (d, n) in written.items())
    log(f"Wrote {summary}. Skipped {skipped} documents already in earlier batches.")
    print(f"Wrote {summary}. Skipped {skipped} documents already in earlier batches.")

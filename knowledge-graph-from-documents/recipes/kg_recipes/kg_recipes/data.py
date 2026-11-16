"""Read assets and datasets as plain rows, with who gave each answer.

On the cluster, answers are read from the Prodigy database the same way the built-in
annotation dashboard reads them, which also says who gave each answer: the person's
session or the agent's or action's name. Each answer comes back as a plain task dict.

For a local run, set ``KG_EXPORTS`` to a folder of ``<dataset>.jsonl`` files of plain
task dicts, each with its annotator in ``_annotator_id``.
"""

import json
import os
import re
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

EXPORTS_ENV = "KG_EXPORTS"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

Answer = Tuple[dict, Optional[str]]


def read_jsonl(path: Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    n = 0
    with Path(path).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def flatten(row: dict) -> dict:
    """A plain task dict from an exported structured example; plain rows are returned as they are."""
    if "__class__" not in row and "input" not in row:
        return row
    flat = {**(row.get("input") or {}), **(row.get("server_anns") or {})}
    flat.update({k: v for k, v in (row.get("user_anns") or {}).items() if v is not None})
    flat.update(row.get("extras") or {})
    for key in ("meta", "answer", "input_hash", "task_hash"):
        if key in row:
            flat[{"input_hash": "_input_hash", "task_hash": "_task_hash"}.get(key, key)] = row[key]
    return flat


def read_assets(paths: Iterable[str]) -> List[dict]:
    return [row for path in paths for row in read_jsonl(Path(path))]


def actor(annotator: Optional[str]) -> Optional[str]:
    """Who gave an answer. An agent or action records its own name; a person's session
    name is ``{dataset}-{task}-{person}[-{sitting}]``, and the person is the second id."""
    ids = UUID_RE.findall(annotator or "")
    return ids[1] if len(ids) >= 2 else annotator


def read_dataset(name: str) -> List[Answer]:
    """Every answer in the dataset, as a plain task dict with the id of who gave it."""
    exports = os.environ.get(EXPORTS_ENV)
    if exports:
        path = Path(exports) / f"{name}.jsonl"
        if not path.exists():
            return []
        rows = [flatten(row) for row in read_jsonl(path)]
        return [(row, actor(row.get("_annotator_id") or row.get("_session_id"))) for row in rows]
    # Imported here: the built-in recipes package is in the recipe image, not always locally.
    from ellf_recipes.recipes.services.annotation_dashboard.analytics import load_dataset

    read = load_dataset(name)
    if read.error or read.unsupported:
        raise RuntimeError(f"Couldn't read dataset {name}: {read.error or read.unsupported}")
    return [(eg.to_unst(), actor(who)) for eg, who in zip(read.examples, read.annotators)]


def read_datasets(names: Iterable[str]) -> List[Answer]:
    return [answer for name in names for answer in read_dataset(name)]


def accepted(answers: Iterable[Answer]) -> Iterator[Answer]:
    for eg, who in answers:
        if eg.get("answer") == "accept":
            yield eg, who

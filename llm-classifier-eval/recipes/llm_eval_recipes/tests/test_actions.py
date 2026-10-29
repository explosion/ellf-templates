import json
import uuid
from pathlib import Path
from typing import Any, Iterable

import pytest
from prodigy.components.db import Database
from prodigy.structured_types import TextcatChoiceExample

from ellf_recipes_sdk import Input, InputDataset, Labels
from llm_eval_recipes.recipes.llm_sample import llm_eval_sample
from llm_eval_recipes.recipes.llm_score import llm_eval_score

OPTIONS = ["GREEN", "RED", "UNCLEAR"]


class FakeOutput:
    """Stands in for an Output asset: keeps what the action writes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rows: list[dict[str, Any]] = []

    def write_jsonl(self, rows: Iterable[dict[str, Any]]) -> int:
        self.rows = list(rows)
        return len(self.rows)


def _ids() -> dict[str, Any]:
    return {"id": uuid.uuid4(), "cluster_id": uuid.uuid4(), "version": "0.0.0"}


def _input(tmp_path: Path, name: str, rows: list[dict[str, Any]]) -> Input:
    path = tmp_path / f"{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return Input(name=name, path=str(path), meta={"loader": "jsonl"}, **_ids())


def _labels(tmp_path: Path, names: list[str]) -> Labels:
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({n: {} for n in names}), encoding="utf-8")
    return Labels(name="annotation-labels", path=str(path), meta={}, **_ids())


def _dataset(name: str) -> InputDataset:
    return InputDataset(id=uuid.uuid4(), name=name, cluster_id=uuid.uuid4())


def _annotate(db: Database, dataset: str, labels: dict[str, str]) -> None:
    db.add_dataset(dataset, structured=True)
    for text, label in labels.items():
        eg = TextcatChoiceExample.from_unst_user(
            {
                "text": text,
                "options": [{"id": o, "text": o} for o in OPTIONS],
                "accept": [label],
                "answer": "accept",
                "config": {"view_id": "choice"},
            }
        )
        db.add_st_examples([eg], [dataset], session_id=f"{dataset}-{uuid.uuid4()}")


def _sample(tmp_path: Path) -> dict[str, FakeOutput]:
    records = [{"text": f"t{i}", "meta": {"reference_label": "RED" if i < 10 else "GREEN"}} for i in range(100)]
    outputs = {n: FakeOutput(f"eval-{n}") for n in ("blind", "pilot", "second", "sample")}
    llm_eval_sample(
        records=_input(tmp_path, "records", records),
        label_scheme=_labels(tmp_path, OPTIONS),
        size=20,
        min_per_label=5,
        pilot_size=4,
        second_size=6,
        **outputs,
    )
    return outputs


def test_sample_action_writes_the_four_assets(tmp_path: Path, capsys):
    outputs = _sample(tmp_path)
    assert len(outputs["pilot"].rows) == 4
    assert len(outputs["second"].rows) == 6
    assert all(set(r["meta"]) == {"id"} for r in outputs["blind"].rows)
    strata = {r["meta"]["stratum"] for r in outputs["sample"].rows}
    assert strata == {"GREEN", "RED"}
    assert sum(r["meta"]["weight"] for r in outputs["sample"].rows) == pytest.approx(100)
    out = capsys.readouterr().out
    assert "Records: 100" in out and "Wrote 4 rows to the asset 'eval-pilot'" in out


def test_score_action_reports_from_the_datasets(database: Database, tmp_path: Path, capsys):
    outputs = _sample(tmp_path)
    texts = [r["text"] for r in outputs["blind"].rows]
    # The annotator says GREEN for everything: right on the GREEN texts
    _annotate(database, "eval_annotations", {t: "GREEN" for t in texts})
    gold = FakeOutput("eval-gold")
    llm_eval_score(
        annotations=_dataset("eval_annotations"),
        sample=_input(tmp_path, "eval-sample", outputs["sample"].rows),
        gold=gold,  # type: ignore[arg-type]
        bootstrap=0,
        show=1,
    )
    out = capsys.readouterr().out
    # The LLM is right on the 90% of traffic it calls GREEN, wrong on the 10% it calls RED
    assert "Accuracy: 90.0%" in out
    assert "GREEN -> RED" in out
    assert len(gold.rows) == len(texts)
    assert {r["meta"]["gold_label"] for r in gold.rows} == {"GREEN"}


def test_score_action_uses_adjudication_second_annotator_and_predictions(
    database: Database, tmp_path: Path, capsys
):
    outputs = _sample(tmp_path)
    sample_rows = outputs["sample"].rows
    llm = {r["text"]: r["meta"]["reference_label"] for r in sample_rows}
    texts = list(llm)
    _annotate(database, "eval_annotations", {t: "UNCLEAR" for t in texts})
    _annotate(database, "eval_adjudication", dict(llm))
    _annotate(database, "eval_second", {t: llm[t] for t in texts[:6]})
    predictions = _input(tmp_path, "eval-predictions", [{"text": t, "meta": {"reference_label": "GREEN"}} for t in texts])
    llm_eval_score(
        annotations=_dataset("eval_annotations"),
        sample=_input(tmp_path, "eval-sample", sample_rows),
        adjudication=_dataset("eval_adjudication"),
        second=_dataset("eval_second"),
        bootstrap=0,
    )
    out = capsys.readouterr().out
    # The adjudication settles every text the LLM's way
    assert "Accuracy: 100.0%" in out
    assert "Texts annotated by both: 6" in out
    llm_eval_score(
        annotations=_dataset("eval_annotations"),
        sample=_input(tmp_path, "eval-sample", sample_rows),
        adjudication=_dataset("eval_adjudication"),
        predictions=predictions,
        bootstrap=0,
    )
    out = capsys.readouterr().out
    assert "Scoring the predictions" in out
    assert "Accuracy: 90.0%" in out

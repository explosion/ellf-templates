import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from prodigy.components.db import Database
from prodigy.errors import RecipeError
from prodigy.structured_types import TextcatChoiceExample

from ellf_recipes_sdk import Dataset, Input, InputDataset
from llm_eval_recipes.recipes.llm_review import llm_choice, llm_review

TASK = "01a0ce59-26bf-7cd1-8a1b-e41bd607d240"
ALEX = "01a0ce06-d43c-7e10-95fa-d0aaca2b8790"
SAM = "01a0ce06-d43c-7e10-95fa-d0aaca2b8791"
COLOURS = ["GREEN", "RED", "UNCLEAR"]


def _choice(text: str, accept: list[str], options: list[str]) -> TextcatChoiceExample:
    return TextcatChoiceExample.from_unst_user(
        {
            "text": text,
            "options": [{"id": o, "text": o} for o in options],
            "accept": accept,
            "answer": "accept",
            "config": {"view_id": "choice"},
        }
    )


def _annotate(
    db: Database, dataset: str, actor: str, text: str, label: str, options=COLOURS
) -> None:
    db.add_dataset(dataset, structured=True)
    session = f"{dataset}-{TASK}-{actor}-{uuid.uuid4()}"
    db.add_st_examples([_choice(text, [label], options)], [dataset], session_id=session)


def _llm_labels(tmp_path: Path, labels: dict[str, Any]) -> Input:
    path = tmp_path / "llm.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for text, label in labels.items():
            f.write(json.dumps({"text": text, "meta": {"reference_label": label}}) + "\n")
    return Input(
        id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        name="eval-sample",
        version="0.0.0",
        path=str(path),
        meta={"loader": "jsonl"},
    )


def _review(names: list[str], llm: Input) -> dict[str, Any]:
    return llm_review(
        dataset=Dataset(id=uuid.uuid4(), name="eval_adjudication", cluster_id=uuid.uuid4()),
        annotations=[
            InputDataset(id=uuid.uuid4(), name=n, cluster_id=uuid.uuid4()) for n in names
        ],
        sample=llm,
    )


def _versions(task: TextcatChoiceExample) -> dict[str, list[str]]:
    return {
        "+".join(v["accept"]): v["sessions"] for v in task.extras["versions"]
    }


def test_reviews_disagreements_and_unclear_only(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "agrees", "GREEN")
    _annotate(database, "eval_annotations", ALEX, "differs", "RED")
    _annotate(database, "eval_annotations", ALEX, "unsure", "UNCLEAR")
    llm = _llm_labels(tmp_path, {"agrees": "GREEN", "differs": "GREEN", "unsure": "RED"})
    components = _review(["eval_annotations"], llm)
    tasks = {t.input.text: t for t in components["stream"]}
    assert set(tasks) == {"differs", "unsure"}
    assert all(isinstance(t, TextcatChoiceExample) for t in tasks.values())
    assert _versions(tasks["differs"]) == {"RED": ["eval_annotations"], "GREEN": ["LLM"]}
    assert _versions(tasks["unsure"]) == {"UNCLEAR": ["eval_annotations"], "RED": ["LLM"]}
    assert components["view_id"] == "review"
    assert components["config"]["labels"] == COLOURS


def test_annotator_version_is_the_default(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "differs", "RED")
    llm = _llm_labels(tmp_path, {"differs": "GREEN"})
    (task,) = list(_review(["eval_annotations"], llm)["stream"])
    (default,) = [v for v in task.extras["versions"] if v["default"]]
    assert default["sessions"] == ["eval_annotations"]


def test_one_label_maps_other_llm_labels_to_not(database: Database, tmp_path: Path):
    options = ["FRAUD", "NOT_FRAUD", "UNCLEAR"]
    _annotate(database, "eval_annotations", ALEX, "fine", "NOT_FRAUD", options)
    _annotate(database, "eval_annotations", ALEX, "missed", "FRAUD", options)
    llm = _llm_labels(tmp_path, {"fine": "OK", "missed": "OK"})
    tasks = {t.input.text: t for t in _review(["eval_annotations"], llm)["stream"]}
    assert set(tasks) == {"missed"}
    assert _versions(tasks["missed"]) == {"FRAUD": ["eval_annotations"], "NOT_FRAUD": ["LLM"]}


def test_second_annotator_shows_as_their_own_version(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "split", "GREEN")
    _annotate(database, "eval_second", SAM, "split", "RED")
    _annotate(database, "eval_annotations", ALEX, "both agree", "GREEN")
    _annotate(database, "eval_second", SAM, "both agree", "GREEN")
    llm = _llm_labels(tmp_path, {"split": "GREEN", "both agree": "GREEN"})
    tasks = {t.input.text: t for t in _review(["eval_annotations", "eval_second"], llm)["stream"]}
    assert set(tasks) == {"split"}
    assert _versions(tasks["split"]) == {
        "GREEN": ["LLM", "eval_annotations"],
        "RED": ["eval_second"],
    }


def test_one_persons_sittings_count_once(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "differs", "RED")
    _annotate(database, "eval_annotations", ALEX, "differs", "RED")
    llm = _llm_labels(tmp_path, {"differs": "GREEN"})
    (task,) = list(_review(["eval_annotations"], llm)["stream"])
    assert _versions(task) == {"RED": ["eval_annotations"], "GREEN": ["LLM"]}


def test_refuses_when_nothing_disagrees(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "agrees", "GREEN")
    llm = _llm_labels(tmp_path, {"agrees": "GREEN"})
    with pytest.raises(RecipeError, match="Nothing to review"):
        _review(["eval_annotations"], llm)


def test_refuses_when_no_annotations_yet(database: Database, tmp_path: Path):
    database.add_dataset("eval_annotations")
    with pytest.raises(RecipeError, match="empty"):
        _review(["eval_annotations"], _llm_labels(tmp_path, {}))


def test_skips_a_second_annotator_who_has_not_started(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "differs", "RED")
    database.add_dataset("eval_second")
    llm = _llm_labels(tmp_path, {"differs": "GREEN"})
    (task,) = list(_review(["eval_annotations", "eval_second"], llm)["stream"])
    assert _versions(task) == {"RED": ["eval_annotations"], "GREEN": ["LLM"]}


def test_reviewed_answer_saves_as_a_choice_example(database: Database, tmp_path: Path):
    _annotate(database, "eval_annotations", ALEX, "differs", "RED")
    llm = _llm_labels(tmp_path, {"differs": "GREEN"})
    components = _review(["eval_annotations"], llm)
    (task,) = list(components["stream"])
    answer = task.to_dict()
    answer["user_anns"] = {"accept": ["GREEN"]}
    answer["answer"] = "accept"
    reviewed = TextcatChoiceExample.from_dict(answer)
    database.add_dataset(components["dataset"], structured=True)
    database.add_st_examples([reviewed], [components["dataset"]], session_id="reviewer")
    (saved,) = database.get_st_dataset_examples(components["dataset"])
    assert isinstance(saved, TextcatChoiceExample) and saved.user_anns is not None
    assert saved.user_anns.accept == ["GREEN"]


@pytest.mark.parametrize(
    "value,ids,expected",
    [
        ("GREEN", COLOURS, ["GREEN"]),
        (["B", "A"], ["A", "B", "UNCLEAR"], ["A", "B"]),
        ("OTHER", ["X", "NOT_X", "UNCLEAR"], ["NOT_X"]),
        ("OTHER", COLOURS, []),
    ],
)
def test_llm_choice(value, ids, expected):
    assert llm_choice(value, ids) == expected

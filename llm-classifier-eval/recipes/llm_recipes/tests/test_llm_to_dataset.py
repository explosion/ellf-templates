import json
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest
from prodigy.components.db import Database
from prodigy.structured_types import TextcatChoiceExample, TextcatExample

from ellf_recipes_sdk import Dataset, Input, LabelScheme
from llm_recipes.recipes import llm_to_dataset as module
from llm_recipes.recipes.llm_to_dataset import classify, llm_to_dataset


def _input(tmp_path: Path, texts: list[str]) -> Input:
    path = tmp_path / "texts.jsonl"
    path.write_text("".join(json.dumps({"text": t}) + "\n" for t in texts), encoding="utf-8")
    return Input(
        id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        name="eval-texts",
        version="0.0.0",
        path=str(path),
        meta={"loader": "jsonl"},
    )


def _output() -> Dataset:
    return Dataset(id=uuid.uuid4(), name="eval_llm", cluster_id=uuid.uuid4())


def _answers(monkeypatch, answers: dict[str, Optional[list[str]]]) -> None:
    monkeypatch.setattr(module, "classify", lambda eg, scheme, exclusive, **kw: answers[eg["text"]])


def _sessions(db: Database, name: str) -> set[str]:
    return {session for session, _ in db.iter_st_dataset_session_examples(name)}


def test_saves_choice_answers_credited_to_the_llm(database: Database, tmp_path: Path, monkeypatch, capsys):
    _answers(monkeypatch, {"a": ["GREEN"], "b": ["RED"], "c": None})
    llm_to_dataset(input=_input(tmp_path, ["a", "b", "c"]), label=["GREEN", "RED"], output=_output(), labels_exclusive=True)
    saved = {eg.input.text: eg for eg in database.get_st_dataset_examples("eval_llm")}
    assert set(saved) == {"a", "b"}
    assert all(isinstance(eg, TextcatChoiceExample) for eg in saved.values())
    assert saved["b"].user_anns is not None and saved["b"].user_anns.accept == ["RED"]
    assert [o.id for o in saved["a"].server_anns.options] == ["GREEN", "RED"]
    assert _sessions(database, "eval_llm") == {"LLM"}
    assert "1 of 3 texts have no usable answer" in capsys.readouterr().out


def test_one_label_saves_accept_or_reject(database: Database, tmp_path: Path, monkeypatch):
    _answers(monkeypatch, {"a": ["FRAUD"], "b": []})
    llm_to_dataset(input=_input(tmp_path, ["a", "b"]), label=["FRAUD"], output=_output())
    saved = {eg.input.text: eg for eg in database.get_st_dataset_examples("eval_llm")}
    assert all(isinstance(eg, TextcatExample) for eg in saved.values())
    assert saved["a"].answer == "accept" and saved["b"].answer == "reject"


def test_annotator_name_can_be_changed(database: Database, tmp_path: Path, monkeypatch):
    _answers(monkeypatch, {"a": ["GREEN"]})
    llm_to_dataset(input=_input(tmp_path, ["a"]), label=["GREEN", "RED"], output=_output(), session="gpt-prompt-v2")
    assert _sessions(database, "eval_llm") == {"gpt-prompt-v2"}


def _client(reply: str, seen: list[dict[str, Any]]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.Client(base_url="https://llm.test/v1", transport=httpx.MockTransport(handle))


SCHEME = LabelScheme.from_json({"GREEN": {"description": "Clearly yes."}, "RED": {"description": "Clearly no."}})


@pytest.mark.parametrize(
    "reply,exclusive,expected",
    [
        ("GREEN", True, ["GREEN"]),
        (" RED ", True, ["RED"]),
        ("GREEN, RED", False, ["GREEN", "RED"]),
        ("GREEN, RED", True, None),
        ("NONE", False, []),
        ("Probably green", True, None),
    ],
)
def test_default_classify_reads_the_reply(reply, exclusive, expected):
    seen: list[dict[str, Any]] = []
    eg = {"text": "Do you have a licence? Yes."}
    got = classify(eg, SCHEME, exclusive, client=_client(reply, seen), model="m", instructions="Grade the reply.")
    assert got == expected
    prompt = seen[0]["messages"][0]["content"]
    assert seen[0]["model"] == "m"
    assert "Grade the reply." in prompt and "- GREEN: Clearly yes." in prompt and eg["text"] in prompt


class FakeOutput:
    """Stands in for an Output asset: keeps what the action writes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rows: list[dict[str, Any]] = []

    def write_jsonl(self, rows) -> int:
        self.rows = list(rows)
        return len(self.rows)


def _records(tmp_path: Path, labels: list[Any]) -> Input:
    path = tmp_path / "records.jsonl"
    rows = [{"text": f"t{i}", "meta": {"id": i, "reference_label": label}} for i, label in enumerate(labels)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return Input(
        id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        name="eval-records",
        version="0.0.0",
        path=str(path),
        meta={"loader": "jsonl"},
    )


def _no_calls(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("classify shouldn't be called for logged labels")

    monkeypatch.setattr(module, "classify", fail)


def test_reads_logged_labels_without_calling_the_llm(database: Database, tmp_path: Path, monkeypatch, capsys):
    _no_calls(monkeypatch)
    records = _records(tmp_path, ["GREEN", "RED", "PURPLE", None])
    llm_to_dataset(input=records, label=["GREEN", "RED"], output=_output(), labels_exclusive=True, llm_label_key="reference_label")
    saved = {eg.input.text: eg.user_anns.accept for eg in database.get_st_dataset_examples("eval_llm")}
    assert saved == {"t0": ["GREEN"], "t1": ["RED"]}
    out = capsys.readouterr().out
    assert "2 of 4 texts have no usable answer" in out
    assert "annotators will see them" in out


def test_logged_labels_for_one_label(database: Database, tmp_path: Path, monkeypatch):
    _no_calls(monkeypatch)
    records = _records(tmp_path, ["FRAUD", "OK", ["FRAUD", "OTHER"]])
    llm_to_dataset(input=records, label=["FRAUD"], output=_output(), llm_label_key="reference_label")
    saved = {eg.input.text: eg.answer for eg in database.get_st_dataset_examples("eval_llm")}
    assert saved == {"t0": "accept", "t1": "reject", "t2": "accept"}


def test_samples_by_label_with_weights_and_a_blind_asset(database: Database, tmp_path: Path, monkeypatch):
    _no_calls(monkeypatch)
    records = _records(tmp_path, ["RED"] * 10 + ["GREEN"] * 90)
    blind = FakeOutput("eval-blind")
    llm_to_dataset(
        input=records,
        label=["GREEN", "RED"],
        output=_output(),
        labels_exclusive=True,
        llm_label_key="reference_label",
        sample_size=20,
        min_per_label=5,
        blind=blind,  # type: ignore[arg-type]
    )
    saved = database.get_st_dataset_examples("eval_llm")
    by_label: dict[str, list[float]] = {}
    for eg in saved:
        by_label.setdefault(eg.user_anns.accept[0], []).append(eg.meta["weight"])
    assert {k: len(v) for k, v in by_label.items()} == {"GREEN": 18, "RED": 5}
    assert by_label["GREEN"] == pytest.approx([90 / 18] * 18)
    assert by_label["RED"] == pytest.approx([10 / 5] * 5)
    assert sum(w for ws in by_label.values() for w in ws) == pytest.approx(100)
    assert {r["text"] for r in blind.rows} == {eg.input.text for eg in saved}
    assert all("reference_label" not in r["meta"] and "weight" not in r["meta"] for r in blind.rows)
    assert all("id" in r["meta"] for r in blind.rows)


def test_without_sampling_every_text_is_saved_unweighted(database: Database, tmp_path: Path, monkeypatch):
    _no_calls(monkeypatch)
    llm_to_dataset(input=_records(tmp_path, ["GREEN", "RED"]), label=["GREEN", "RED"], output=_output(), llm_label_key="reference_label")
    assert all("weight" not in eg.meta for eg in database.get_st_dataset_examples("eval_llm"))


def test_refuses_when_no_text_has_an_answer(database: Database, tmp_path: Path, monkeypatch):
    _no_calls(monkeypatch)
    with pytest.raises(ValueError, match="No text has a usable answer"):
        llm_to_dataset(input=_records(tmp_path, ["PURPLE"]), label=["GREEN", "RED"], output=_output(), llm_label_key="reference_label")

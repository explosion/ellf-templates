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
    assert "1 texts got no usable answer" in capsys.readouterr().out


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

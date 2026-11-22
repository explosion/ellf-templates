import json
import uuid
from collections import Counter

import pytest
import spacy
from prodigy.errors import RecipeError
from prodigy.structured_types import SpansManualExample

from ellf_recipes_sdk import Asset, Input, InputDataset, save_examples

from jackknife_recipes.recipes.jackknife_folds import assign_folds, jackknife_folds

CLUSTER = uuid.UUID(int=0)
NAMES = ["Anna Weber", "Paul Martin", "Lea Roux", "Jan Novak", "Eva Berg", "Tom Wolf"]


def task(name, *, labelled=True, answer="accept"):
    text = f"Die Klage von {name} wurde abgewiesen."
    doc = spacy.blank("de").make_doc(text)
    tokens = [
        {"text": t.text, "start": t.idx, "end": t.idx + len(t), "id": t.i, "ws": bool(t.whitespace_)}
        for t in doc
    ]
    start = text.index(name)
    span = doc.char_span(start, start + len(name))
    assert span is not None
    spans = (
        [{"start": span.start_char, "end": span.end_char, "label": "PERSON", "token_start": span.start, "token_end": span.end - 1}]
        if labelled
        else []
    )
    return {"text": text, "tokens": tokens, "spans": spans, "answer": answer, "meta": {"doc": name}}


def annotated(name, tasks):
    save_examples(name, tasks, session_id="anna", parse_as=SpansManualExample, view_id="ner_manual")
    return InputDataset(id=uuid.uuid4(), name=name, cluster_id=CLUSTER)


@pytest.fixture
def assets(monkeypatch, tmp_path):
    registered = {}
    monkeypatch.setenv("ELLF_BUILTIN_PATH_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(Asset, "exists", classmethod(lambda cls, name: name in registered))
    monkeypatch.setattr(
        Input,
        "create",
        classmethod(
            lambda cls, name, path, loader, version="0.0.0", meta=None: registered.setdefault(
                name, {"path": path.replace("{__data__}", str(tmp_path / "data")), "meta": meta}
            )
        ),
    )
    return registered


def rows(asset):
    with open(asset["path"]) as f:
        return [json.loads(line) for line in f]


def spans_of(db, name):
    return {
        eg.to_unst()["meta"]["doc"]: [(s["start"], s["end"], s["label"]) for s in eg.to_unst()["spans"]]
        for _, eg in db.iter_st_dataset_session_examples(name)
    }


def test_folds_are_even_and_stable():
    hashes = list(range(10))
    fold_of = assign_folds(hashes, 3, seed=0)
    assert sorted(Counter(fold_of.values()).values()) == [3, 3, 4]
    assert fold_of == assign_folds(list(reversed(hashes)), 3, seed=0)
    assert fold_of != assign_folds(hashes, 3, seed=1)


def test_split_writes_each_fold_and_a_gold_copy(database, assets):
    source = annotated("gold-src", [task(n) for n in NAMES] + [task("Ute Kern", answer="ignore")])
    jackknife_folds(annotations=source, prefix="jk-r1", folds=3)
    every = spans_of(database, "jk-r1")
    assert sorted(every) == sorted(NAMES)
    folds = [spans_of(database, f"jk-r1-fold-{k}") for k in (1, 2, 3)]
    assert [len(f) for f in folds] == [2, 2, 2]
    assert {doc for f in folds for doc in f} == set(NAMES)
    for k, fold in enumerate(folds, start=1):
        texts = rows(assets[f"jk-r1-fold-{k}-texts"])
        assert {r["meta"]["doc"] for r in texts} == set(fold)
        assert all(r["tokens"] and "spans" not in r and r["meta"]["fold"] == k for r in texts)
    sessions = {sid for sid, _ in database.iter_st_dataset_session_examples("jk-r1")}
    assert sessions == {"gold"}


def test_split_refuses_before_writing(database, assets):
    source = annotated("gold-src", [task(n) for n in NAMES[:2]])
    with pytest.raises(RecipeError, match="fewer than the 3 folds"):
        jackknife_folds(annotations=source, prefix="jk-r1", folds=3)
    assert "jk-r1" not in database
    jackknife_folds(annotations=source, prefix="jk-r1", folds=2)
    with pytest.raises(RecipeError, match="already exist"):
        jackknife_folds(annotations=source, prefix="jk-r1", folds=2)
    with pytest.raises(RecipeError, match="can't be an output"):
        jackknife_folds(annotations=source, prefix="gold-src", folds=2)


def test_split_refuses_conflicting_and_binary_annotations(database, assets):
    source = annotated("dual", [task("Anna Weber")])
    save_examples("dual", [task("Anna Weber", labelled=False)], session_id="paul", parse_as=SpansManualExample, view_id="ner_manual")
    with pytest.raises(RecipeError, match="1 texts .* differ"):
        jackknife_folds(annotations=source, prefix="jk-r1", folds=2)
    save_examples("binary", [task("Anna Weber")], session_id="anna", parse_as=SpansManualExample, view_id="ner")
    with pytest.raises(RecipeError, match="'ner' interface"):
        jackknife_folds(annotations=InputDataset(id=uuid.uuid4(), name="binary", cluster_id=CLUSTER), prefix="jk-r2", folds=2)


def test_a_round_reviews_only_disagreements_and_splits_again(database, assets):
    """The template's round: predictions imported beside the gold copy, the
    built-in review auto-accepting agreements, and its answers split again."""
    review_module = pytest.importorskip("ellf_recipes.recipes.review")
    from ellf_recipes.recipes.corrections.import_annotations import import_annotations
    from ellf_recipes_sdk import Dataset

    source = annotated("gold-src", [task(n) for n in NAMES])
    jackknife_folds(annotations=source, prefix="jk-r1", folds=2)
    wrong = "Lea Roux"
    for k in (1, 2):
        predicted = []
        for row in rows(assets[f"jk-r1-fold-{k}-texts"]):
            pred = task(row["meta"]["doc"], labelled=row["meta"]["doc"] != wrong)
            predicted.append({**pred, "meta": row["meta"], "_input_hash": row["_input_hash"], "_annotator_id": "de_pipeline"})
        path = assets[f"jk-r1-fold-{k}-texts"]["path"].replace("texts", "preds")
        with open(path, "w") as f:
            f.write("\n".join(json.dumps(p) for p in predicted))
        import_annotations(
            annotations=Input(id=uuid.uuid4(), cluster_id=CLUSTER, name=f"p{k}", version="1", path=path, meta={"loader": "jsonl"}),
            dataset=Dataset(id=uuid.uuid4(), name="jk-r1", cluster_id=CLUSTER),
            annotator=f"jk-r1-fold-{k}",
        )
    settings = review_module.review(
        dataset=Dataset(id=uuid.uuid4(), name="jk-r1-reviewed", cluster_id=CLUSTER),
        datasets=[InputDataset(id=uuid.uuid4(), name="jk-r1", cluster_id=CLUSTER)],
        auto_accept=True,
    )
    shown = list(settings["stream"])
    assert [eg.to_unst()["meta"]["doc"] for eg in shown] == [wrong]
    assert len(spans_of(database, "jk-r1-reviewed")) == len(NAMES) - 1
    (review_task,) = shown
    review_task.answer = "accept"
    database.add_st_examples([review_task], datasets="jk-r1-reviewed", session_id="jk-r1-reviewed-bojan")

    reviewed = InputDataset(id=uuid.uuid4(), name="jk-r1-reviewed", cluster_id=CLUSTER)
    jackknife_folds(annotations=reviewed, prefix="jk-r2", folds=2)
    assert spans_of(database, "jk-r2") == spans_of(database, "gold-src")

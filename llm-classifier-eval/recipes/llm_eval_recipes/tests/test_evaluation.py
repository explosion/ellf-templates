import random

import pytest

from llm_eval_recipes import evaluation
from llm_eval_recipes.evaluation import Scheme

LABELS = ["BILLING", "TECHNICAL", "FRAUD"]
# What the LLM says, given the true label
CONFUSION = {
    "BILLING": [("BILLING", 0.92), ("TECHNICAL", 0.06), ("FRAUD", 0.02)],
    "TECHNICAL": [("BILLING", 0.10), ("TECHNICAL", 0.88), ("FRAUD", 0.02)],
    "FRAUD": [("BILLING", 0.25), ("TECHNICAL", 0.05), ("FRAUD", 0.70)],
}


def _draw(rng: random.Random, dist: list[tuple[str, float]]) -> str:
    x, acc = rng.random(), 0.0
    for label, p in dist:
        acc += p
        if x < acc:
            return label
    return dist[-1][0]


def _population(n: int = 20000, seed: int = 1) -> tuple[list[dict], dict[str, str]]:
    """Records with a rare label, and the true label of each text."""
    rng = random.Random(seed)
    truth_dist = [("BILLING", 0.62), ("TECHNICAL", 0.35), ("FRAUD", 0.03)]
    records, truth = [], {}
    for i in range(n):
        true = _draw(rng, truth_dist)
        text = f"record {i}"
        truth[text] = true
        llm = _draw(rng, CONFUSION[true])
        records.append({"text": text, "meta": {"reference_label": llm}})
    return records, truth


def _annotations(texts: list[str], truth: dict[str, str]) -> list[dict]:
    return [
        {"input": {"text": t}, "answer": "accept", "user_anns": {"accept": [truth[t]]}}
        for t in texts
    ]


@pytest.mark.parametrize(
    "ids,mode,names",
    [
        (["FRAUD", "NOT_FRAUD", "UNCLEAR"], "binary", ["FRAUD"]),
        (["GREEN", "RED", "UNCLEAR"], "choice", ["GREEN", "RED"]),
        (["APPLICABLE", "NOT_APPLICABLE", "OTHER", "UNCLEAR"], "choice", ["APPLICABLE", "NOT_APPLICABLE", "OTHER"]),
    ],
)
def test_scheme_from_options(ids, mode, names):
    scheme = evaluation.scheme_from_options(ids, "UNCLEAR", exclusive=True)
    assert (scheme.mode, scheme.names) == (mode, names)


def test_draw_sample_stratifies_with_a_minimum_and_weights():
    records, _ = _population()
    scheme = Scheme(LABELS, "choice")
    drawn = evaluation.draw_sample(records, scheme, size=300, min_per_label=40, pilot=50, second=50)
    counts = {s: n for s, (_, n, _) in drawn.strata.items()}
    assert counts["FRAUD"] == 40
    for n, k, weight in drawn.strata.values():
        assert weight == pytest.approx(n / k)
    assert sum(r["meta"]["weight"] for r in drawn.sampled) == pytest.approx(len(records))
    assert all(set(r["meta"]) == {"id"} for r in drawn.blind)
    blind_texts = {r["text"] for r in drawn.blind}
    assert {r["text"] for r in drawn.pilot} <= blind_texts
    assert {r["text"] for r in drawn.second} <= blind_texts
    assert len(drawn.pilot) == len(drawn.second) == 50


def test_draw_sample_keeps_duplicate_decisions_and_skips_incomplete_ones():
    records = [{"text": "same", "meta": {"reference_label": "A"}}] * 3
    records += [{"text": "", "meta": {"reference_label": "A"}}, {"text": "no label"}]
    drawn = evaluation.draw_sample(records, Scheme(["A", "B"], "choice"), size=10, min_per_label=1, pilot=1, second=1)
    assert len(drawn.sampled) == 3
    assert len(drawn.blind) == 1
    assert drawn.skipped == 2


def test_draw_sample_maps_one_label():
    records = [{"text": f"t{i}", "meta": {"reference_label": "OK" if i % 2 else "FRAUD"}} for i in range(10)]
    drawn = evaluation.draw_sample(records, Scheme(["FRAUD"], "binary"), size=10, min_per_label=1, pilot=0, second=0)
    assert set(drawn.strata) == {"FRAUD", "NOT_FRAUD"}


def test_weighted_estimates_are_unbiased():
    """Over many samples, the weighted estimates average out to the figures
    over the whole population."""
    records, truth = _population()
    scheme = Scheme(LABELS, "choice")
    true_accuracy = sum(r["meta"]["reference_label"] == truth[r["text"]] for r in records) / len(records)
    estimates = []
    for seed in range(20):
        drawn = evaluation.draw_sample(records, scheme, size=300, min_per_label=40, pilot=0, second=0, seed=seed)
        sampled = evaluation.read_sampled(drawn.sampled)
        answers = evaluation.read_answers(_annotations([s.text for s in sampled], truth), scheme, "UNCLEAR")
        gold = evaluation.gold_labels(answers)
        rows = [evaluation.Scored(s.stratum, s.weight, s.stratum, gold[s.id]) for s in sampled]
        estimates.append(evaluation.metrics(rows, scheme)["accuracy"])
    assert sum(estimates) / len(estimates) == pytest.approx(true_accuracy, abs=0.01)


def test_score_report_uses_adjudication_and_predictions():
    sampled = evaluation.read_sampled(
        [
            {"text": "a", "meta": {"stratum": "GREEN", "weight": 1.0}},
            {"text": "b", "meta": {"stratum": "GREEN", "weight": 1.0}},
            {"text": "c", "meta": {"stratum": "RED", "weight": 2.0}},
        ]
    )
    scheme = Scheme(["GREEN", "RED"], "choice")
    annotations = evaluation.read_answers(
        [
            {"input": {"text": "a"}, "answer": "accept", "user_anns": {"accept": ["GREEN"]}},
            {"input": {"text": "b"}, "answer": "accept", "user_anns": {"accept": ["UNCLEAR"]}},
            {"input": {"text": "c"}, "answer": "accept", "user_anns": {"accept": ["GREEN"]}},
        ],
        scheme,
        "UNCLEAR",
    )
    settled = evaluation.read_answers(
        [{"input": {"text": "b"}, "answer": "accept", "user_anns": {"accept": ["RED"]}}],
        scheme,
        "UNCLEAR",
    )
    gold = evaluation.gold_labels(annotations, settled)
    report = "\n".join(evaluation.score_report(sampled, gold, scheme, unclear="UNCLEAR", n_bootstrap=0))
    # a right (weight 1), b wrong (1), c wrong (2)
    assert "Accuracy: 25.0%" in report
    predictions = {evaluation.text_id(t): "GREEN" for t in "abc"}
    rescored = "\n".join(evaluation.score_report(sampled, gold, scheme, unclear="UNCLEAR", predictions=predictions, n_bootstrap=0))
    # a right (1), b wrong (1), c right (2)
    assert "Scoring the predictions" in rescored and "Accuracy: 75.0%" in rescored


def test_read_sampled_needs_the_sample_action_output():
    with pytest.raises(ValueError, match="llm_eval_sample"):
        evaluation.read_sampled([{"text": "a", "meta": {"reference_label": "X"}}])


def test_gold_rows_merge_duplicates_and_drop_unclear():
    sampled = evaluation.read_sampled(
        [
            {"text": "a", "meta": {"stratum": "GREEN", "weight": 1.5}},
            {"text": "a", "meta": {"stratum": "GREEN", "weight": 1.5}},
            {"text": "b", "meta": {"stratum": "RED", "weight": 1.0}},
        ]
    )
    gold = {evaluation.text_id("a"): "RED", evaluation.text_id("b"): "UNCLEAR"}
    (row,) = evaluation.gold_rows(sampled, gold, "UNCLEAR")
    assert row == {"text": "a", "meta": {"gold_label": "RED", "llm_label": "GREEN", "weight": 3.0}}

"""Sample an LLM classifier's decisions and score it against people's labels,
weighted to its traffic.

Records are the LLM's past decisions: the text it saw and its raw label in
`meta.reference_label`. `draw_sample` stratifies them by the LLM's label and
returns the blind texts for annotation and the sampled records with their
stratum and weight in `meta`. The scoring reads those sampled records, and
annotation rows from text classification datasets, structured as
`InputDataset.load()` and `ellf datasets export` give them. Everything is
joined on a hash of the text.

Standard library only, so it can be tested and used without Prodigy.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Union

Row = dict[str, Any]


@dataclass
class Scheme:
    """How labels are compared: one label X is X or NOT_X, several exclusive
    labels are one of them, and several non-exclusive ones are a sorted set
    written `A+B`."""

    names: list[str]
    mode: str

    def key(self, value: Union[str, list, None]) -> str:
        if self.mode == "binary":
            (name,) = self.names
            if isinstance(value, list):
                return name if name in value else f"NOT_{name}"
            return name if value == name else f"NOT_{name}"
        if isinstance(value, list):
            return "+".join(sorted(str(v) for v in value))
        return "" if value is None else str(value)

    def labels_of(self, key: str) -> set[str]:
        if self.mode == "binary":
            return {key} & set(self.names)
        return {k for k in key.split("+") if k}


@dataclass
class Sampled:
    id: str
    text: str
    stratum: str
    weight: float


@dataclass
class Scored:
    stratum: str
    weight: float
    predicted: str
    gold: str


def text_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def row_text(row: Row) -> str:
    return (row.get("input") or {}).get("text") or row.get("text") or ""


def scheme_from_options(option_ids: Iterable[str], unclear: str, exclusive: bool) -> Scheme:
    """The scheme an annotation task's options imply: one label X with NOT_X
    is a yes/no classifier."""
    ids = [i for i in option_ids if i != unclear]
    positives = [i for i in ids if not (i.startswith("NOT_") and i[4:] in ids)]
    if len(positives) == 1 and len(ids) == 2:
        return Scheme(positives, "binary")
    return Scheme(ids, "choice" if exclusive else "multi")


def option_ids(rows: Iterable[Row]) -> list[str]:
    """The options of the first annotation row that has any."""
    for row in rows:
        options = (row.get("server_anns") or {}).get("options") or row.get("options")
        if options:
            return [str(o["id"]) for o in options]
    return []


@dataclass
class Drawn:
    """A stratified sample: the sampled records with their stratum and weight,
    the blind texts (each once, shuffled, with only an id), random subsets of
    them for a pilot and a second annotator, and a summary per stratum of
    (records, sampled, weight)."""

    sampled: list[Row]
    blind: list[Row]
    pilot: list[Row]
    second: list[Row]
    strata: dict[str, tuple[int, int, float]]
    skipped: int


def draw_sample(
    records: Iterable[Row],
    scheme: Scheme,
    *,
    size: int,
    min_per_label: int,
    pilot: int,
    second: int,
    seed: int = 0,
) -> Drawn:
    """Sample the records separately within each LLM label: each label gets its
    share of `size`, and at least `min_per_label`, so rare labels can be
    measured. Each sampled record's weight brings it back to its share of all
    records."""
    rng = random.Random(seed)
    strata: defaultdict[str, list[Row]] = defaultdict(list)
    skipped = 0
    for row in records:
        meta = row.get("meta") or {}
        if not row.get("text") or "reference_label" not in meta:
            skipped += 1
            continue
        strata[scheme.key(meta["reference_label"])].append(row)
    total = sum(len(rows) for rows in strata.values())
    if not total:
        raise ValueError("No records with a text and meta.reference_label to sample from.")
    sampled: list[Row] = []
    blind: dict[str, str] = {}
    summary = {}
    for stratum in sorted(strata, key=lambda s: -len(strata[s])):
        rows = strata[stratum]
        n = min(len(rows), max(min_per_label, round(size * len(rows) / total)))
        weight = len(rows) / n
        for row in rng.sample(rows, n):
            meta = {**(row.get("meta") or {}), "stratum": stratum, "weight": weight}
            sampled.append({"text": row["text"], "meta": meta})
            blind.setdefault(text_id(row["text"]), row["text"])
        summary[stratum] = (len(rows), n, weight)
    ids = list(blind)
    rng.shuffle(ids)
    blind_rows = [{"text": blind[i], "meta": {"id": i}} for i in ids]
    return Drawn(
        sampled=sampled,
        blind=blind_rows,
        pilot=blind_rows[:pilot],
        second=rng.sample(blind_rows, min(second, len(blind_rows))),
        strata=summary,
        skipped=skipped,
    )


def read_sampled(rows: Iterable[Row]) -> list[Sampled]:
    sampled = []
    for row in rows:
        meta = row.get("meta") or {}
        if "stratum" not in meta or "weight" not in meta:
            raise ValueError(
                "The sample has no stratum or weight in meta: build it with the "
                "llm_eval_sample action."
            )
        text = row_text(row)
        sampled.append(Sampled(text_id(text), text, str(meta["stratum"]), float(meta["weight"])))
    return sampled


def read_answers(rows: Iterable[Row], scheme: Scheme, unclear: str) -> dict[str, tuple[str, str]]:
    """Each annotated text's label and the text itself, by id. The latest
    answer counts where a text was annotated more than once."""
    answers: dict[str, tuple[int, str, str]] = {}
    for row in rows:
        answer = row.get("answer")
        user_anns = row.get("user_anns") or {}
        if "accept" in user_anns:
            if answer != "accept":
                continue
            accepted = user_anns["accept"] or []
            if unclear in accepted:
                label = unclear
            elif scheme.mode == "binary":
                label = accepted[0] if accepted else ""
            else:
                label = scheme.key(accepted)
        elif answer in ("accept", "reject"):
            (name,) = scheme.names
            label = name if answer == "accept" else f"NOT_{name}"
        else:
            continue
        text = row_text(row)
        id_ = text_id(text)
        timestamp = (row.get("extras") or {}).get("_timestamp") or 0
        if id_ not in answers or timestamp >= answers[id_][0]:
            answers[id_] = (timestamp, label, text)
    return {id_: (label, text) for id_, (_, label, text) in answers.items()}


def gold_labels(
    annotations: dict[str, tuple[str, str]],
    adjudication: Optional[dict[str, tuple[str, str]]] = None,
) -> dict[str, str]:
    """Gold label by id: the annotations, overruled by the adjudication."""
    gold = {id_: label for id_, (label, _) in annotations.items()}
    for id_, (label, _) in (adjudication or {}).items():
        gold[id_] = label
    return gold


def metrics(rows: list[Scored], scheme: Scheme) -> dict[str, float]:
    total = sum(r.weight for r in rows)
    out = {"accuracy": sum(r.weight for r in rows if r.predicted == r.gold) / total}
    for name in scheme.names:
        tp = fp = fn = predicted_rate = true_rate = 0.0
        for r in rows:
            p = name in scheme.labels_of(r.predicted)
            g = name in scheme.labels_of(r.gold)
            tp += r.weight * (p and g)
            fp += r.weight * (p and not g)
            fn += r.weight * (g and not p)
            predicted_rate += r.weight * p
            true_rate += r.weight * g
        precision = tp / (tp + fp) if tp + fp else float("nan")
        recall = tp / (tp + fn) if tp + fn else float("nan")
        if tp:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0 if tp + fp and tp + fn else float("nan")
        out[f"{name}:precision"] = precision
        out[f"{name}:recall"] = recall
        out[f"{name}:f1"] = f1
        out[f"{name}:predicted_rate"] = predicted_rate / total
        out[f"{name}:true_rate"] = true_rate / total
    return out


def bootstrap(
    rows: list[Scored], scheme: Scheme, n: int, seed: int = 0
) -> dict[str, tuple[float, float]]:
    """95% intervals from resampling records within each stratum."""
    rng = random.Random(seed)
    by_stratum: defaultdict[str, list[Scored]] = defaultdict(list)
    for r in rows:
        by_stratum[r.stratum].append(r)
    draws: defaultdict[str, list[float]] = defaultdict(list)
    for _ in range(n):
        resample = [rng.choice(group) for group in by_stratum.values() for _ in group]
        for k, v in metrics(resample, scheme).items():
            if v == v:
                draws[k].append(v)
    intervals = {}
    for k, values in draws.items():
        values.sort()
        intervals[k] = (
            values[int(0.025 * (len(values) - 1))],
            values[int(0.975 * (len(values) - 1))],
        )
    return intervals


def fmt(value: float, interval: Optional[tuple[float, float]] = None) -> str:
    if value != value:
        return "-"
    if interval is None:
        return f"{value:.1%}"
    return f"{value:.1%} ({interval[0]:.0%}-{interval[1]:.0%})"


def score_report(
    sampled: list[Sampled],
    gold: dict[str, str],
    scheme: Scheme,
    *,
    unclear: str,
    predictions: Optional[dict[str, str]] = None,
    show: int = 0,
    n_bootstrap: int = 1000,
    seed: int = 0,
) -> list[str]:
    """The score of the LLM, or of other predictions on the same texts, against
    the gold labels, as report lines."""
    rows = []
    n_unclear = unannotated = unpredicted = 0
    for s in sampled:
        label = gold.get(s.id)
        if label is None:
            unannotated += 1
            continue
        if label == unclear:
            n_unclear += 1
            continue
        predicted = s.stratum
        if predictions is not None:
            if s.id not in predictions:
                unpredicted += 1
                continue
            predicted = predictions[s.id]
        rows.append(Scored(s.stratum, s.weight, predicted, label))
    if not rows:
        return ["No sampled records have a gold label yet."]
    source = "the predictions" if predictions is not None else "the LLM"
    lines = [f"Scoring {source} on {len(rows)} sampled records, weighted to the whole population"]
    if unannotated:
        lines.append(f"  {unannotated} sampled records aren't annotated yet")
    if n_unclear:
        lines.append(f"  {n_unclear} marked {unclear}, left out: settle them in the adjudication")
    if unpredicted:
        lines.append(f"  {unpredicted} have no prediction")
    point = metrics(rows, scheme)
    intervals = bootstrap(rows, scheme, n_bootstrap, seed) if n_bootstrap else {}
    lines.append("")
    lines.append(f"Accuracy: {fmt(point['accuracy'], intervals.get('accuracy'))}")
    lines.append("")
    lines.append("Per label (95% interval):")
    header = ["precision", "recall", "f1", "LLM rate", "true rate"]
    widths = [22, 22, 10, 12, 22]
    lines.append(f"  {'label':<24}" + "".join(f"{h:>{w}}" for h, w in zip(header, widths)))
    for name in scheme.names:
        cells = [
            fmt(point[f"{name}:precision"], intervals.get(f"{name}:precision")),
            fmt(point[f"{name}:recall"], intervals.get(f"{name}:recall")),
            fmt(point[f"{name}:f1"]),
            fmt(point[f"{name}:predicted_rate"]),
            fmt(point[f"{name}:true_rate"], intervals.get(f"{name}:true_rate")),
        ]
        lines.append(f"  {name:<24}" + "".join(f"{c:>{w}}" for c, w in zip(cells, widths)))
    confusions = Counter((r.gold, r.predicted) for r in rows if r.gold != r.predicted)
    lines.append("")
    lines.append("Most common mistakes (gold -> predicted), sampled records:")
    for (g, p), count in confusions.most_common(10):
        lines.append(f"  {g} -> {p}: {count}")
    if show:
        by_pair: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
        seen = set()
        for s in sampled:
            label = gold.get(s.id)
            if label is None or label == unclear or s.id in seen:
                continue
            predicted = predictions.get(s.id) if predictions is not None else s.stratum
            if predicted is not None and predicted != label:
                seen.add(s.id)
                by_pair[(label, predicted)].append(s.text)
        lines.append("")
        lines.append(f"Texts, up to {show} per mistake:")
        for (g, p), _ in confusions.most_common(10):
            lines.append(f"  gold {g}, predicted {p}:")
            for text in by_pair[(g, p)][:show]:
                text = " ".join(text.split())
                lines.append(f"    {text if len(text) <= 300 else text[:297] + '...'}")
    return lines


def agreement_report(first: dict[str, tuple[str, str]], second: dict[str, tuple[str, str]]) -> list[str]:
    """Cohen's kappa and per-label agreement between two annotators on the
    texts both annotated, as report lines."""
    shared = sorted(set(first) & set(second))
    if not shared:
        return ["No text was annotated by both annotators."]
    pairs = [(first[i][0], second[i][0]) for i in shared]
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    a_counts = Counter(a for a, _ in pairs)
    b_counts = Counter(b for _, b in pairs)
    expected = sum(a_counts[k] * b_counts[k] for k in a_counts) / (n * n)
    kappa = 1.0 if expected == 1 else (observed - expected) / (1 - expected)
    lines = [f"Texts annotated by both: {n}", f"Agreement: {observed:.1%}  kappa: {kappa:.3f}"]
    lines.append("Per label: both chose it / either chose it")
    for name in sorted(set(a_counts) | set(b_counts)):
        both = sum(a == b == name for a, b in pairs)
        either = sum(name in (a, b) for a, b in pairs)
        lines.append(f"  {name}: {both} / {either}")
    lines.append("Disagreements (first -> second):")
    for (a, b), count in Counter(p for p in pairs if p[0] != p[1]).most_common(10):
        lines.append(f"  {a} -> {b}: {count}")
    return lines


def gold_rows(sampled: list[Sampled], gold: dict[str, str], unclear: str) -> list[Row]:
    """The gold set: each settled text once, with its gold label, the LLM's
    label and the weight of all its sampled records, in the records format so
    the LLM can be rerun on it."""
    weights: defaultdict[str, float] = defaultdict(float)
    for s in sampled:
        weights[s.id] += s.weight
    rows = []
    seen = set()
    for s in sampled:
        if s.id in seen or s.id not in gold or gold[s.id] == unclear:
            continue
        seen.add(s.id)
        meta = {"gold_label": gold[s.id], "llm_label": s.stratum, "weight": weights[s.id]}
        rows.append({"text": s.text, "meta": meta})
    return rows

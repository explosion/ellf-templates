#!/usr/bin/env python
"""Measure an LLM classifier against people: sample its decisions, score
them against the settled labels, and keep a gold set for re-scoring prompt
changes.

Usage:
    python scripts/llm_eval.py labels <labels.json> --out <annotation_labels.json>
    python scripts/llm_eval.py sample <records.jsonl> --labels <labels.json> --out-dir <dir>
        [--size 300] [--min-per-label 20] [--pilot 50] [--second 50] [--seed 0]
    python scripts/llm_eval.py score --key <key.jsonl> --labels <labels.json>
        --annotations <annotations.jsonl> [--adjudication <adjudication.jsonl>]
        [--predictions <predictions.jsonl>] [--show 10] [--bootstrap 1000]
    python scripts/llm_eval.py agreement <first.jsonl> <second.jsonl> --labels <labels.json>
    python scripts/llm_eval.py gold --key <key.jsonl> --labels <labels.json>
        --annotations <annotations.jsonl> [--adjudication <adjudication.jsonl>] --out <gold.jsonl>

Records are the LLM's past decisions: JSONL with the text the LLM saw in
`text` and its raw label in `meta.reference_label` (a list for labels that
aren't exclusive). Annotations and adjudications are datasets exported with
`ellf datasets export <dataset> -o <file>`. Everything is joined on a hash of
the text.

labels
    The annotation label scheme: the classifier's labels plus UNCLEAR, and for
    one label X, X, NOT_X and UNCLEAR.

sample
    A stratified random sample of the records, by the LLM's label: each label
    gets its share of `--size`, and at least `--min-per-label`, so rare labels
    can be measured. Every sampled record carries the weight that brings it
    back to its share of all records. Writes `blind.jsonl` (each distinct text
    once, shuffled, with only an id), `pilot.jsonl` and `second.jsonl` (random
    subsets of it, for the pilot and a second annotator), `llm_labels.jsonl`
    (each distinct text with the LLM's label, for the `llm_review` recipe that
    adjudicates) and `key.jsonl` (the LLM's label, stratum and weight of each
    sampled record).

score
    The LLM against the gold labels (the annotations, overruled by the
    adjudication where there is one): accuracy, per-label precision, recall and
    F1, and each label's rate as the LLM assigns it against its estimated true
    rate, all weighted to the whole population, with stratified bootstrap 95%
    intervals. `--predictions` scores other predictions on the same gold texts
    instead, e.g. a revised prompt's: JSONL with `text` and `label`. `--show`
    prints texts behind the most common confusions.

agreement
    Cohen's kappa and per-label agreement between two annotators on the texts
    both annotated.

gold
    The gold set to keep: each text with its gold label, the LLM's label and
    its weight. Rerun the LLM on these texts after a prompt change and score
    the new predictions with `score --predictions`.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Union

UNCLEAR_DESCRIPTION = "You could defend more than one answer."


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
class KeyRecord:
    id: str
    llm: str
    stratum: str
    weight: float


def text_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _text(row: dict) -> str:
    return (row.get("input") or {}).get("text") or row.get("text") or ""


def read_scheme(path: Path, exclusive: bool) -> Scheme:
    data = json.loads(path.read_text(encoding="utf-8"))
    names = list(data)
    if len(names) == 1:
        return Scheme(names, "binary")
    return Scheme(names, "choice" if exclusive else "multi")


def read_key(path: Path) -> list[KeyRecord]:
    return [
        KeyRecord(row["id"], row["llm"], row["stratum"], float(row["weight"]))
        for row in read_jsonl(path)
    ]


def read_answers(path: Path, scheme: Scheme, unclear: str) -> dict[str, tuple[str, str]]:
    """Each annotated text's label and the text itself, by id. The latest
    answer counts where a text was annotated more than once."""
    answers: dict[str, tuple[int, str, str]] = {}
    for row in read_jsonl(path):
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
        text = _text(row)
        id_ = text_id(text)
        timestamp = (row.get("extras") or {}).get("_timestamp") or 0
        if id_ not in answers or timestamp >= answers[id_][0]:
            answers[id_] = (timestamp, label, text)
    return {id_: (label, text) for id_, (_, label, text) in answers.items()}


def gold_labels(args, scheme: Scheme) -> tuple[dict[str, str], dict[str, str]]:
    """Gold label and text by id: annotations, overruled by adjudications."""
    answers = read_answers(args.annotations, scheme, args.unclear)
    gold = {id_: label for id_, (label, _) in answers.items()}
    texts = {id_: text for id_, (_, text) in answers.items()}
    if getattr(args, "adjudication", None):
        for id_, (label, text) in read_answers(args.adjudication, scheme, args.unclear).items():
            gold[id_] = label
            texts.setdefault(id_, text)
    return gold, texts


def cmd_labels(args) -> None:
    data = json.loads(args.scheme.read_text(encoding="utf-8"))
    labels = dict(data)
    if len(labels) == 1:
        (name,) = labels
        labels[f"NOT_{name}"] = {"description": f"{name} doesn't apply."}
    labels[args.unclear] = {"description": UNCLEAR_DESCRIPTION}
    args.out.write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {', '.join(labels)} to {args.out}")


def cmd_sample(args) -> None:
    scheme = read_scheme(args.labels, args.exclusive)
    rng = random.Random(args.seed)
    strata: defaultdict[str, list[dict]] = defaultdict(list)
    missing = 0
    for row in read_jsonl(args.records):
        meta = row.get("meta") or {}
        if not row.get("text") or "reference_label" not in meta:
            missing += 1
            continue
        strata[scheme.key(meta["reference_label"])].append(row)
    if missing:
        print(f"Skipped {missing} records without text or meta.reference_label")
    total = sum(len(rows) for rows in strata.values())
    if not total:
        raise SystemExit("No records to sample from.")
    print(f"Records: {total}")
    print("LLM label: records, sampled, weight")
    key = []
    blind: dict[str, str] = {}
    raw: dict[str, object] = {}
    for stratum in sorted(strata, key=lambda s: -len(strata[s])):
        rows = strata[stratum]
        n = min(len(rows), max(args.min_per_label, round(args.size * len(rows) / total)))
        weight = len(rows) / n
        for row in rng.sample(rows, n):
            id_ = text_id(row["text"])
            blind.setdefault(id_, row["text"])
            raw.setdefault(id_, row["meta"]["reference_label"])
            key.append({"id": id_, "llm": stratum, "stratum": stratum, "weight": weight})
        print(f"  {stratum}: {len(rows)}, {n}, {weight:.2f}")
    ids = list(blind)
    rng.shuffle(ids)
    blind_rows = [{"text": blind[i], "meta": {"id": i}} for i in ids]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "blind.jsonl", blind_rows)
    write_jsonl(args.out_dir / "pilot.jsonl", blind_rows[: args.pilot])
    write_jsonl(args.out_dir / "second.jsonl", rng.sample(blind_rows, min(args.second, len(blind_rows))))
    write_jsonl(args.out_dir / "key.jsonl", key)
    write_jsonl(
        args.out_dir / "llm_labels.jsonl",
        [{"text": blind[i], "meta": {"reference_label": raw[i]}} for i in ids],
    )
    print(
        f"Wrote {len(blind_rows)} distinct texts ({len(key)} sampled records) to "
        f"{args.out_dir}/blind.jsonl, {min(args.pilot, len(blind_rows))} to pilot.jsonl, "
        f"{min(args.second, len(blind_rows))} to second.jsonl, the LLM's labels to "
        f"llm_labels.jsonl and the key to key.jsonl"
    )


@dataclass
class Scored:
    stratum: str
    weight: float
    predicted: str
    gold: str


def metrics(rows: list[Scored], scheme: Scheme) -> dict[str, float]:
    total = sum(r.weight for r in rows)
    out = {"accuracy": sum(r.weight for r in rows if r.predicted == r.gold) / total}
    names = scheme.names
    for name in names:
        tp = fp = fn = 0.0
        predicted_rate = true_rate = 0.0
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
        f1 = (
            2 * precision * recall / (precision + recall)
            if tp and precision + recall
            else (0.0 if tp + fp and tp + fn else float("nan"))
        )
        out[f"{name}:precision"] = precision
        out[f"{name}:recall"] = recall
        out[f"{name}:f1"] = f1
        out[f"{name}:predicted_rate"] = predicted_rate / total
        out[f"{name}:true_rate"] = true_rate / total
    return out


def bootstrap(rows: list[Scored], scheme: Scheme, n: int, seed: int) -> dict[str, tuple[float, float]]:
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
        lo = values[int(0.025 * (len(values) - 1))]
        hi = values[int(0.975 * (len(values) - 1))]
        intervals[k] = (lo, hi)
    return intervals


def fmt(value: float, interval: Optional[tuple[float, float]]) -> str:
    if value != value:
        return "-"
    if interval is None:
        return f"{value:.1%}"
    return f"{value:.1%} ({interval[0]:.0%}-{interval[1]:.0%})"


def cmd_score(args) -> None:
    scheme = read_scheme(args.labels, args.exclusive)
    gold, texts = gold_labels(args, scheme)
    key = read_key(args.key)
    predictions: Optional[dict[str, str]] = None
    if args.predictions:
        predictions = {
            text_id(row["text"]): scheme.key(row["label"]) for row in read_jsonl(args.predictions)
        }
    rows = []
    unclear = unannotated = unpredicted = 0
    for k in key:
        label = gold.get(k.id)
        if label is None:
            unannotated += 1
            continue
        if label == args.unclear:
            unclear += 1
            continue
        predicted = k.llm
        if predictions is not None:
            if k.id not in predictions:
                unpredicted += 1
                continue
            predicted = predictions[k.id]
        rows.append(Scored(k.stratum, k.weight, predicted, label))
    if not rows:
        raise SystemExit("No sampled records have a gold label yet.")
    source = "the predictions file" if predictions is not None else "the LLM"
    print(f"Scoring {source} on {len(rows)} sampled records, weighted to the whole population")
    if unannotated:
        print(f"  {unannotated} sampled records aren't annotated yet")
    if unclear:
        print(f"  {unclear} marked {args.unclear}, left out: settle them in the adjudication")
    if unpredicted:
        print(f"  {unpredicted} have no prediction in the predictions file")
    point = metrics(rows, scheme)
    intervals = bootstrap(rows, scheme, args.bootstrap, args.seed) if args.bootstrap else {}
    print(f"\nAccuracy: {fmt(point['accuracy'], intervals.get('accuracy'))}")
    print("\nPer label (95% interval):")
    print(f"  {'label':<24}{'precision':>22}{'recall':>22}{'f1':>10}{'LLM rate':>12}{'true rate':>22}")
    for name in scheme.names:
        cells = [
            fmt(point[f"{name}:precision"], intervals.get(f"{name}:precision")),
            fmt(point[f"{name}:recall"], intervals.get(f"{name}:recall")),
            fmt(point[f"{name}:f1"], None),
            fmt(point[f"{name}:predicted_rate"], None),
            fmt(point[f"{name}:true_rate"], intervals.get(f"{name}:true_rate")),
        ]
        widths = [22, 22, 10, 12, 22]
        print(f"  {name:<24}" + "".join(f"{c:>{w}}" for c, w in zip(cells, widths)))
    confusions = Counter((r.gold, r.predicted) for r in rows if r.gold != r.predicted)
    print("\nMost common mistakes (gold -> predicted), sampled records:")
    for (g, p), count in confusions.most_common(10):
        print(f"  {g} -> {p}: {count}")
    if args.show:
        print(f"\nTexts, up to {args.show} per mistake:")
        by_pair: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
        seen = set()
        for k in key:
            label = gold.get(k.id)
            if label is None or label == args.unclear or k.id in seen:
                continue
            predicted = predictions.get(k.id) if predictions is not None else k.llm
            if predicted is not None and predicted != label:
                seen.add(k.id)
                by_pair[(label, predicted)].append(texts.get(k.id, ""))
        for (g, p), _ in confusions.most_common(10):
            print(f"\n  gold {g}, predicted {p}:")
            for text in by_pair[(g, p)][: args.show]:
                text = " ".join(text.split())
                print(f"    {text if len(text) <= 300 else text[:297] + '...'}")


def cmd_agreement(args) -> None:
    scheme = read_scheme(args.labels, args.exclusive)
    first = read_answers(args.first, scheme, args.unclear)
    second = read_answers(args.second, scheme, args.unclear)
    shared = sorted(set(first) & set(second))
    if not shared:
        raise SystemExit("No text was annotated by both.")
    pairs = [(first[i][0], second[i][0]) for i in shared]
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    a_counts = Counter(a for a, _ in pairs)
    b_counts = Counter(b for _, b in pairs)
    expected = sum(a_counts[k] * b_counts[k] for k in a_counts) / (n * n)
    kappa = 1.0 if expected == 1 else (observed - expected) / (1 - expected)
    print(f"Texts annotated by both: {n}")
    print(f"Agreement: {observed:.1%}  kappa: {kappa:.3f}")
    print("\nPer label: both chose it / either chose it")
    for name in sorted(set(a_counts) | set(b_counts)):
        both = sum(a == b == name for a, b in pairs)
        either = sum(name in (a, b) for a, b in pairs)
        print(f"  {name}: {both} / {either}")
    print("\nDisagreements (first -> second):")
    for (a, b), count in Counter(p for p in pairs if p[0] != p[1]).most_common(10):
        print(f"  {a} -> {b}: {count}")


def cmd_gold(args) -> None:
    scheme = read_scheme(args.labels, args.exclusive)
    gold, texts = gold_labels(args, scheme)
    rows = []
    seen = set()
    weights: defaultdict[str, float] = defaultdict(float)
    for k in read_key(args.key):
        weights[k.id] += k.weight
    for k in read_key(args.key):
        if k.id in seen or k.id not in gold or gold[k.id] == args.unclear:
            continue
        seen.add(k.id)
        rows.append({"text": texts[k.id], "label": gold[k.id], "llm": k.llm, "weight": weights[k.id]})
    write_jsonl(args.out, rows)
    print(f"Wrote {len(rows)} gold texts to {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--unclear", default="UNCLEAR", help="the UNCLEAR label")
    common.add_argument(
        "--exclusive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="several labels are exclusive (default)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser = lambda name, help: sub.add_parser(name, help=help, parents=[common])

    p = add_parser("labels", help="annotation label scheme")
    p.add_argument("scheme", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_labels)

    p = add_parser("sample", help="stratified blind sample")
    p.add_argument("records", type=Path)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--size", type=int, default=300)
    p.add_argument("--min-per-label", type=int, default=20)
    p.add_argument("--pilot", type=int, default=50)
    p.add_argument("--second", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_sample)

    p = add_parser("score", help="score the LLM against the gold labels")
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--annotations", type=Path, required=True)
    p.add_argument("--adjudication", type=Path)
    p.add_argument("--predictions", type=Path)
    p.add_argument("--show", type=int, default=0)
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_score)

    p = add_parser("agreement", help="agreement between two annotators")
    p.add_argument("first", type=Path)
    p.add_argument("second", type=Path)
    p.add_argument("--labels", type=Path, required=True)
    p.set_defaults(func=cmd_agreement)

    p = add_parser("gold", help="the gold set to keep")
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--annotations", type=Path, required=True)
    p.add_argument("--adjudication", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_gold)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

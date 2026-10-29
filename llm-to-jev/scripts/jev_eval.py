#!/usr/bin/env python
"""Compare Jev runs with an existing LLM classifier and with adjudicated records.

Usage:
    python scripts/jev_eval.py labels <labels.json> --out <adjudication_labels.json>
    python scripts/jev_eval.py agreement <run.jsonl> [--cutoffs 0.6,0.7,0.8,0.9]
    python scripts/jev_eval.py sample <run.jsonl> --out <blind.jsonl>
        [--per-pair 6] [--low-confidence 10] [--low-below 0.7] [--seed 0]
    python scripts/jev_eval.py adjudicated <adjudicated.jsonl>
        <name>=<run.jsonl> [<name>=<run.jsonl> ...] [--unclear UNCLEAR]

Every .jsonl file is a dataset exported with
`ellf datasets export <dataset> -o <file>`. A run is the output dataset of a
`textcat_jev` action. Its records keep the input's `meta`, so they carry the
LLM's label as `meta.reference_label`, and optionally a `meta.weight` for
samples that over-represent some labels.

labels
    The adjudication label scheme for a classifier's label scheme: its labels
    plus UNCLEAR, and for a classifier with one label (e.g. NEGATIVE), that
    label, NOT_<LABEL> and UNCLEAR.

agreement
    Agreement and Cohen's kappa between Jev and the LLM, the most common
    disagreements, agreement by Jev's confidence, and how many records each
    confidence cut-off would send to a person. Weighted by `meta.weight`.

sample
    A blind adjudication input from a baseline run: up to `--per-pair` records
    of each kind of disagreement (e.g. "LLM RED, Jev YELLOW"), plus
    `--low-confidence` records where both agree but Jev's confidence is below
    `--low-below`. Written shuffled, with only the text and an id, so the
    annotator sees neither system's answer.

adjudicated
    For each run (e.g. baseline=... rules=...), how many adjudicated records the
    LLM and Jev each match, leaving out those marked UNCLEAR. For the first run,
    also whose answer the annotator chose on the disagreements, and whether the
    low-confidence agreements hold up. Counts on records that rules were
    written from are optimistic.

Records are joined on a hash of their text. A classifier with one label is
compared as that label or NOT_<LABEL>, so a `reference_label` other than the
label counts as NOT_<LABEL>. With several labels that aren't exclusive, a
record's labels are compared as one sorted set, written `A+B`.

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
from typing import Iterator, Union

BANDS = [(0.95, 1.01), (0.9, 0.95), (0.7, 0.9), (0.5, 0.7), (0.0, 0.5)]
UNCLEAR_DESCRIPTION = "You could defend more than one answer."


@dataclass
class JevRecord:
    id: str
    text: str
    reference: str
    jev: str
    confidence: float
    weight: float


def text_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def label_key(value: Union[str, list]) -> str:
    if isinstance(value, list):
        return "+".join(sorted(str(v) for v in value))
    return str(value)


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _text(row: dict) -> str:
    return (row.get("input") or {}).get("text") or row.get("text") or ""


def read_run(path: Path) -> list[JevRecord]:
    """The records of a Jev run that have a reference label."""
    records = []
    missing = 0
    for row in read_jsonl(path):
        meta = row.get("meta") or {}
        reference = meta.get("reference_label")
        if reference is None:
            missing += 1
            continue
        user_anns = row.get("user_anns") or {}
        if "accept" in user_anns:
            jev = label_key(user_anns["accept"])
            reference = label_key(reference)
        else:
            label = (row.get("server_anns") or {}).get("label") or user_anns["label"]
            jev = label if row["answer"] == "accept" else f"NOT_{label}"
            reference = label if reference == label else f"NOT_{label}"
        text = _text(row)
        records.append(
            JevRecord(
                id=text_id(text),
                text=text,
                reference=reference,
                jev=jev,
                confidence=float(meta["jev"]["confidence"]),
                weight=float(meta.get("weight", 1.0)),
            )
        )
    if missing:
        print(f"Skipped {missing} records without meta.reference_label in {path}")
    return records


def read_adjudicated(path: Path, unclear: str) -> dict[str, str]:
    """The annotator's label for each record, by id. Where a record was
    annotated more than once, the latest answer counts."""
    labels: dict[str, tuple[int, str]] = {}
    for row in read_jsonl(path):
        if row.get("answer") != "accept":
            continue
        accepted = (row.get("user_anns") or {}).get("accept") or []
        if not accepted:
            continue
        label = unclear if unclear in accepted else label_key(accepted)
        id_ = text_id(_text(row))
        timestamp = (row.get("extras") or {}).get("_timestamp") or 0
        if id_ not in labels or timestamp >= labels[id_][0]:
            labels[id_] = (timestamp, label)
    return {id_: label for id_, (_, label) in labels.items()}


def adjudication_labels(scheme: Union[dict, list], unclear: str) -> dict:
    if isinstance(scheme, list):
        scheme = {name: {} for name in scheme}
    labels = dict(scheme)
    if len(labels) == 1:
        (name,) = labels
        labels[f"NOT_{name}"] = {"description": f"{name} doesn't apply."}
    labels[unclear] = {"description": UNCLEAR_DESCRIPTION}
    return labels


def kappa(pairs: list[tuple[str, str, float]]) -> float:
    total = sum(w for _, _, w in pairs)
    observed = sum(w for a, b, w in pairs if a == b) / total
    a_weights: defaultdict[str, float] = defaultdict(float)
    b_weights: defaultdict[str, float] = defaultdict(float)
    for a, b, w in pairs:
        a_weights[a] += w
        b_weights[b] += w
    expected = sum(a_weights[k] * b_weights[k] for k in a_weights) / (total * total)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(records: list[JevRecord], cutoffs: list[float]) -> None:
    total = sum(r.weight for r in records)
    pairs = [(r.reference, r.jev, r.weight) for r in records]
    agree = sum(w for a, b, w in pairs if a == b)
    weighted = any(r.weight != 1.0 for r in records)
    note = " (shares weighted by meta.weight)" if weighted else ""
    print(f"Records: {len(records)}{note}")
    print(f"Agreement: {agree / total:.1%}  kappa: {kappa(pairs):.3f}")
    print("\nMost common disagreements (LLM -> Jev), records:")
    disagreements = Counter((a, b) for a, b, _ in pairs if a != b)
    for (a, b), count in disagreements.most_common(10):
        print(f"  {a} -> {b}: {count}")
    print("\nAgreement by Jev confidence:")
    for lo, hi in BANDS:
        band = [r for r in records if lo <= r.confidence < hi]
        if band:
            band_total = sum(r.weight for r in band)
            rate = sum(r.weight for r in band if r.reference == r.jev) / band_total
            print(f"  {lo:.2f}-{min(hi, 1.0):.2f}: {len(band):>6} records, {rate:.1%}")
    print("\nSent to a person at each cut-off:")
    for cutoff in cutoffs:
        below = [r for r in records if r.confidence < cutoff]
        share = sum(r.weight for r in below) / total
        print(f"  {cutoff}: {len(below)} records ({share:.0%})")


def sample(
    records: list[JevRecord],
    out: Path,
    *,
    per_pair: int,
    low_confidence: int,
    low_below: float,
    seed: int,
) -> None:
    rng = random.Random(seed)
    pairs = defaultdict(list)
    low = []
    for r in records:
        if r.reference != r.jev:
            pairs[(r.reference, r.jev)].append(r)
        elif r.confidence < low_below:
            low.append(r)
    picked = []
    print("Disagreements (LLM -> Jev): sampled / total")
    for (ref, jev), group in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
        take = rng.sample(group, min(per_pair, len(group)))
        picked.extend(take)
        print(f"  {ref} -> {jev}: {len(take)} / {len(group)}")
    take = rng.sample(low, min(low_confidence, len(low)))
    picked.extend(take)
    print(f"Agreements below {low_below}: {len(take)} / {len(low)}")
    rng.shuffle(picked)
    with out.open("w", encoding="utf-8") as f:
        for r in picked:
            row = {"text": r.text, "meta": {"id": r.id}}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(picked)} records to {out}")


def adjudicated(
    labels: dict[str, str], runs: list[tuple[str, list[JevRecord]]], unclear: str
) -> None:
    judged = {k: v for k, v in labels.items() if v != unclear}
    print(f"Adjudicated: {len(labels)}, {len(labels) - len(judged)} {unclear}")
    first_name, first = runs[0]
    by_id = {r.id: r for r in first}
    missing = [k for k in labels if k not in by_id]
    if missing:
        print(f"{len(missing)} adjudicated records aren't in run '{first_name}'")
    llm = sum(by_id[k].reference == v for k, v in judged.items() if k in by_id)
    print(f"\nMatches with the annotator (of {len(judged)}):")
    print(f"  LLM: {llm}")
    for name, records in runs:
        run = {r.id: r for r in records}
        matches = sum(run[k].jev == v for k, v in judged.items() if k in run)
        print(f"  Jev {name}: {matches}")

    disagree: Counter = Counter()
    agree: Counter = Counter()
    for k, label in labels.items():
        r = by_id.get(k)
        if r is None:
            continue
        if r.reference != r.jev:
            if label == unclear:
                disagree[unclear] += 1
            elif label == r.jev:
                disagree["Jev's answer"] += 1
            elif label == r.reference:
                disagree["the LLM's answer"] += 1
            else:
                disagree["neither"] += 1
        elif label == unclear:
            agree[unclear] += 1
        elif label == r.jev:
            agree["the same as both"] += 1
        else:
            agree["different from both"] += 1
    print(f"\nDisagreements in '{first_name}', annotator chose:")
    for key, count in disagree.most_common():
        print(f"  {key}: {count}")
    print(f"\nAgreements in '{first_name}', annotator's answer:")
    for key, count in agree.most_common():
        print(f"  {key}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("mode", choices=["labels", "agreement", "sample", "adjudicated"])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", type=Path, help="file to write (labels, sample)")
    parser.add_argument("--cutoffs", default="0.6,0.7,0.8,0.9")
    parser.add_argument("--per-pair", type=int, default=6)
    parser.add_argument("--low-confidence", type=int, default=10)
    parser.add_argument("--low-below", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--unclear", default="UNCLEAR")
    args = parser.parse_args()

    if args.mode == "adjudicated":
        if len(args.files) < 2 or any("=" not in f for f in args.files[1:]):
            parser.error("adjudicated takes an export, then one or more name=run")
        labels = read_adjudicated(Path(args.files[0]), args.unclear)
        runs = []
        for spec in args.files[1:]:
            name, path = spec.split("=", 1)
            runs.append((name, read_run(Path(path))))
        adjudicated(labels, runs, args.unclear)
        return
    if len(args.files) != 1:
        parser.error(f"{args.mode} takes one file")
    path = Path(args.files[0])
    if args.mode in ("labels", "sample") and args.out is None:
        parser.error(f"{args.mode} needs --out")
    if args.mode == "labels":
        scheme = json.loads(path.read_text(encoding="utf-8"))
        result = adjudication_labels(scheme, args.unclear)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote {', '.join(result)} to {args.out}")
    elif args.mode == "agreement":
        agreement(read_run(path), [float(c) for c in args.cutoffs.split(",")])
    else:
        sample(
            read_run(path),
            args.out,
            per_pair=args.per_pair,
            low_confidence=args.low_confidence,
            low_below=args.low_below,
            seed=args.seed,
        )


if __name__ == "__main__":
    main()

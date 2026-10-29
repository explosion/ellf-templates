#!/usr/bin/env python
"""Compare Jev with an existing LLM classifier, tune it from annotations, and
export the configuration.

Usage:
    python scripts/jev_eval.py labels <labels.json> --out <annotation_labels.json>
    python scripts/jev_eval.py agreement <run.jsonl>
    python scripts/jev_eval.py sample <run.jsonl> --out <blind.jsonl> --key <key.jsonl>
        [--disagreements 150] [--random 0] [--seed 0]
    python scripts/jev_eval.py adjudicated <annotations.jsonl> <name>=<run.jsonl> ...
        [--key <key.jsonl>] [--show 10]
    python scripts/jev_eval.py thresholds <annotations.jsonl> <run.jsonl> [--key <key.jsonl>]
    python scripts/jev_eval.py config --labels <labels.json> --instructions <file>
        --run <run.jsonl> --out <jev_config.json> [--exclusive] [--threshold LABEL=0.8 ...]
    python scripts/jev_eval.py drift <before.jsonl> <after.jsonl>

Every .jsonl file except a key is a dataset exported with
`ellf datasets export <dataset> -o <file>`. A run is the output dataset of a
`textcat_jev` action. Its records keep the input's `meta`: the LLM's label as
`meta.reference_label`, and optionally a `meta.weight` for samples that
over-represent some labels. Annotations are the dataset of a task over a blind
sample written by `sample`, which also writes a key saying which records were
drawn at random.

labels
    The annotation label scheme for a classifier's label scheme: its labels
    plus UNCLEAR, and for one label X, X, NOT_X and UNCLEAR.

agreement
    Agreement and Cohen's kappa between Jev and the LLM, the most common
    disagreements, and agreement by Jev's confidence.

sample
    A blind annotation sample. `--random` records are drawn at random from the
    whole run, then `--disagreements` records are spread as evenly as possible
    over the kinds of disagreement (e.g. "LLM RED, Jev YELLOW"). Written
    shuffled, with only the text and an id, so the annotator sees neither
    system's answer. Records without a reference label can only be drawn at
    random.

adjudicated
    For each run (e.g. baseline=... rules=...), how many annotated records the
    LLM and Jev each match, leaving out those marked UNCLEAR; whose answer the
    annotator chose on the first run's disagreements; and with the key, each
    system's accuracy on the random sample. `--show` prints, for the last run,
    the texts where Jev is wrong and the LLM right, where both are wrong, and
    those marked UNCLEAR: the material for rules.

thresholds
    Jev's estimated accuracy at each threshold. Annotated records are weighted
    up by how many records of their kind (LLM label, Jev label) they stand for,
    and agreements nobody annotated count as correct, so the estimate covers
    the whole run. It's unbiased for the run the sample was drawn from; for a
    later run, also check the random-sample figures (with the key). With one
    label, or several that aren't exclusive, it sweeps the probability a label
    needs to be applied. With a choice between labels, it gives the precision
    of each label above each confidence cut-off, for a per-label cut-off below
    which your system falls back to something else.

config
    The configuration to run Jev outside Ellf: the endpoint, the model version
    the run used, the questions exactly as the `textcat_jev` action sends them,
    and the thresholds with the decision rule.

drift
    How Jev's labels and confidence on new records compare with an earlier run.

Records are joined on a hash of their text. A classifier with one label is
compared as that label or NOT_<LABEL>. With several labels that aren't
exclusive, a record's labels are compared as one sorted set, written `A+B`.

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

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
BANDS = [(0.95, 1.01), (0.9, 0.95), (0.7, 0.9), (0.5, 0.7), (0.0, 0.5)]
SWEEP = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
CUTOFFS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]
UNCLEAR_DESCRIPTION = "You could defend more than one answer."

Known = list[tuple["JevRecord", str, float]]


@dataclass
class JevRecord:
    id: str
    text: str
    reference: Optional[str]
    jev: str
    confidence: float
    weight: float
    mode: str
    probabilities: dict[str, float]
    model: str


def text_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def label_key(value: Union[str, list]) -> str:
    if isinstance(value, list):
        return "+".join(sorted(str(v) for v in value))
    return str(value)


def label_set(key: str, record: JevRecord) -> set[str]:
    """The labels a label key applies, for one label or several that aren't
    exclusive."""
    if record.mode == "binary":
        return set(record.probabilities) & {key}
    return {k for k in key.split("+") if k}


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _text(row: dict) -> str:
    return (row.get("input") or {}).get("text") or row.get("text") or ""


def read_run(path: Path) -> list[JevRecord]:
    records = []
    for row in read_jsonl(path):
        meta = row.get("meta") or {}
        jev_meta = meta["jev"]
        reference = meta.get("reference_label")
        user_anns = row.get("user_anns") or {}
        if "accept" in user_anns:
            accepted = user_anns["accept"]
            multi = isinstance(reference, list) or len(accepted) != 1
            mode = "multi" if multi else "choice"
            jev = label_key(accepted)
            if reference is not None:
                reference = label_key(reference)
        else:
            mode = "binary"
            label = (row.get("server_anns") or {}).get("label") or user_anns["label"]
            jev = label if row["answer"] == "accept" else f"NOT_{label}"
            if reference is not None:
                reference = label if reference == label else f"NOT_{label}"
        probabilities = jev_meta["probabilities"]
        text = _text(row)
        records.append(
            JevRecord(
                id=text_id(text),
                text=text,
                reference=reference,
                jev=jev,
                confidence=float(jev_meta["confidence"]),
                weight=float(meta.get("weight", 1.0)),
                mode=mode,
                probabilities={k: float(v) for k, v in probabilities.items()},
                model=jev_meta.get("model", ""),
            )
        )
    return records


def read_annotations(path: Path, unclear: str) -> dict[str, str]:
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


def read_key(path: Optional[Path]) -> set[str]:
    if path is None:
        return set()
    return {row["id"] for row in read_jsonl(path) if row.get("random")}


def share(part: float, total: float) -> str:
    return f"{part / total:.1%}" if total else "-"


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


def cmd_labels(args) -> None:
    scheme = json.loads(args.scheme.read_text(encoding="utf-8"))
    if isinstance(scheme, list):
        scheme = {name: {} for name in scheme}
    labels = dict(scheme)
    if len(labels) == 1:
        (name,) = labels
        labels[f"NOT_{name}"] = {"description": f"{name} doesn't apply."}
    labels[args.unclear] = {"description": UNCLEAR_DESCRIPTION}
    args.out.write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {', '.join(labels)} to {args.out}")


def cmd_agreement(args) -> None:
    records = [r for r in read_run(args.run) if r.reference is not None]
    if not records:
        raise SystemExit("No records with meta.reference_label in the run.")
    total = sum(r.weight for r in records)
    pairs = [(r.reference or "", r.jev, r.weight) for r in records]
    agree = sum(w for a, b, w in pairs if a == b)
    weighted = any(r.weight != 1.0 for r in records)
    note = " (shares weighted by meta.weight)" if weighted else ""
    print(f"Records: {len(records)}{note}")
    print(f"Agreement: {share(agree, total)}  kappa: {kappa(pairs):.3f}")
    print("\nMost common disagreements (LLM -> Jev), records:")
    disagreements = Counter((a, b) for a, b, _ in pairs if a != b)
    for (a, b), count in disagreements.most_common(10):
        print(f"  {a} -> {b}: {count}")
    print("\nAgreement by Jev confidence:")
    for lo, hi in BANDS:
        band = [r for r in records if lo <= r.confidence < hi]
        if band:
            band_total = sum(r.weight for r in band)
            band_agree = sum(r.weight for r in band if r.reference == r.jev)
            rate = share(band_agree, band_total)
            print(f"  {lo:.2f}-{min(hi, 1.0):.2f}: {len(band):>6} records, {rate}")


def cmd_sample(args) -> None:
    rng = random.Random(args.seed)
    records = read_run(args.run)
    picked = rng.sample(records, min(args.random, len(records)))
    taken = {r.id for r in picked}
    key = [{"id": r.id, "random": True} for r in picked]
    pairs: defaultdict[tuple[str, str], list[JevRecord]] = defaultdict(list)
    for r in records:
        if r.reference is not None and r.reference != r.jev and r.id not in taken:
            pairs[(r.reference, r.jev)].append(r)
    for group in pairs.values():
        rng.shuffle(group)
    # Round-robin, so every kind of disagreement gets a few before any gets many
    order = sorted(pairs, key=lambda p: (len(pairs[p]), p))
    chosen: Counter = Counter()
    budget = args.disagreements
    while budget > 0 and any(chosen[p] < len(pairs[p]) for p in order):
        for p in order:
            if budget > 0 and chosen[p] < len(pairs[p]):
                chosen[p] += 1
                budget -= 1
    print(f"Random: {len(picked)} of {len(records)}")
    print("Disagreements (LLM -> Jev): sampled / total")
    for p in sorted(order, key=lambda p: -len(pairs[p])):
        group = pairs[p][: chosen[p]]
        picked.extend(group)
        key.extend({"id": r.id, "random": False} for r in group)
        print(f"  {p[0]} -> {p[1]}: {chosen[p]} / {len(pairs[p])}")
    rng.shuffle(picked)
    with args.out.open("w", encoding="utf-8") as f:
        for r in picked:
            row = {"text": r.text, "meta": {"id": r.id}}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with args.key.open("w", encoding="utf-8") as f:
        for row in key:
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(picked)} records to {args.out} and the key to {args.key}")


def _show(title: str, records: list[JevRecord], labels: dict[str, str], n: int) -> None:
    print(f"\n{title}: {len(records)}")
    for r in records[:n]:
        text = " ".join(r.text.split())
        text = text if len(text) <= 300 else text[:297] + "..."
        answers = f"LLM {r.reference} | Jev {r.jev} {r.confidence:.2f}"
        print(f"  [{answers} | annotator {labels[r.id]}] {text}")


def cmd_adjudicated(args) -> None:
    labels = read_annotations(args.annotations, args.unclear)
    randoms = read_key(args.key)
    runs = []
    for spec in args.runs:
        if "=" not in spec:
            raise SystemExit(f"Expected <name>=<run.jsonl>, got {spec}")
        name, path = spec.split("=", 1)
        runs.append((name, {r.id: r for r in read_run(Path(path))}))
    judged = {k: v for k, v in labels.items() if v != args.unclear}
    print(f"Annotated: {len(labels)}, {len(labels) - len(judged)} {args.unclear}")
    first_name, first = runs[0]
    missing = [k for k in labels if k not in first]
    if missing:
        print(f"{len(missing)} annotated records aren't in run '{first_name}'")

    def matches(run: dict[str, JevRecord], ids: dict[str, str], llm: bool) -> str:
        found = [k for k in ids if k in run]
        hit = sum((run[k].reference if llm else run[k].jev) == ids[k] for k in found)
        return f"{hit} of {len(found)}"

    has_reference = any(r.reference is not None for r in first.values())
    print("\nMatches with the annotator:")
    if has_reference:
        print(f"  LLM: {matches(first, judged, True)}")
    for name, run in runs:
        print(f"  Jev {name}: {matches(run, judged, False)}")
    random_judged = {k: v for k, v in judged.items() if k in randoms}
    if random_judged:
        print(f"\nAccuracy on the random sample ({len(random_judged)} records):")
        if has_reference:
            print(f"  LLM: {matches(first, random_judged, True)}")
        for name, run in runs:
            print(f"  Jev {name}: {matches(run, random_judged, False)}")

    if has_reference:
        disagree: Counter = Counter()
        for k, label in labels.items():
            r = first.get(k)
            if r is None or r.reference == r.jev:
                continue
            if label == args.unclear:
                disagree[args.unclear] += 1
            elif label == r.jev:
                disagree["Jev's answer"] += 1
            elif label == r.reference:
                disagree["the LLM's answer"] += 1
            else:
                disagree["neither"] += 1
        print(f"\nDisagreements in '{first_name}', annotator chose:")
        for key, count in disagree.most_common():
            print(f"  {key}: {count}")

    if args.show:
        last_name, last = runs[-1]
        annotated = [last[k] for k in labels if k in last]
        unclear = args.unclear
        print(f"\nTexts from '{last_name}', up to {args.show} of each:")
        jev_wrong = [r for r in annotated if labels[r.id] == r.reference != r.jev]
        both_wrong = [
            r for r in annotated if labels[r.id] not in (unclear, r.jev, r.reference)
        ]
        marked = [r for r in annotated if labels[r.id] == unclear]
        _show("Jev wrong, LLM right", jev_wrong, labels, args.show)
        _show("Both wrong", both_wrong, labels, args.show)
        _show(unclear, marked, labels, args.show)


def estimate(
    records: list[JevRecord], judged: dict[str, str], randoms: set[str]
) -> tuple[Known, float]:
    """Each record that has a known label, with the weight it stands for:
    annotated disagreements weighted up to the size of their kind, agreements
    weighted up from the random sample, and other agreements taken as correct.
    Agreements annotated for another reason (e.g. low confidence) aren't a fair
    draw of their kind, so only random ones count. Also returns the weight left
    out: disagreements of a kind nobody annotated."""
    groups: defaultdict[tuple[Optional[str], str], list[JevRecord]] = defaultdict(list)
    for r in records:
        groups[(r.reference, r.jev)].append(r)
    known: Known = []
    left_out = 0.0
    for (ref, jev), group in groups.items():
        total = sum(r.weight for r in group)
        drawn = randoms if ref == jev else judged
        hits = [r for r in group if r.id in judged and r.id in drawn]
        if hits:
            scale = total / sum(r.weight for r in hits)
            known.extend((r, judged[r.id], r.weight * scale) for r in hits)
        elif ref == jev:
            known.extend((r, jev, r.weight) for r in group)
        else:
            left_out += total
    return known, left_out


def _report_choice(known: Known) -> None:
    total = sum(w for _, _, w in known)
    overall = sum(w for r, truth, w in known if r.jev == truth)
    print(f"  Accuracy: {share(overall, total)}")
    print("  Precision of each label above a confidence cut-off (share answered):")
    print("    " + "label".ljust(24) + "".join(f"{c:>18}" for c in CUTOFFS))
    for name in sorted({r.jev for r, _, _ in known}):
        cells = []
        for cutoff in CUTOFFS:
            above = [
                (r, t, w) for r, t, w in known if r.jev == name and r.confidence >= cutoff
            ]
            weight = sum(w for _, _, w in above)
            right = sum(w for r, t, w in above if t == r.jev)
            cells.append(f"{share(right, weight)} ({share(weight, total)})")
        print("    " + name.ljust(24) + "".join(f"{c:>18}" for c in cells))


def _report_sweep(known: Known) -> None:
    total = sum(w for _, _, w in known)
    for label in sorted(known[0][0].probabilities):
        print(f"  {label}: applied when p >= threshold")
        print("    threshold  accuracy  precision  recall  applied")
        for t in SWEEP:
            tp = fp = fn = right = applied = 0.0
            for r, truth, w in known:
                predicted = r.probabilities.get(label, 0.0) >= t
                actual = label in label_set(truth, r)
                right += w * (predicted == actual)
                applied += w * predicted
                tp += w * (predicted and actual)
                fp += w * (predicted and not actual)
                fn += w * (actual and not predicted)
            print(
                f"    {t:>9}  {share(right, total):>8}  {share(tp, tp + fp):>9}"
                f"  {share(tp, tp + fn):>6}  {share(applied, total):>7}"
            )


def _report_thresholds(known: Known) -> None:
    if known[0][0].mode == "choice":
        _report_choice(known)
    else:
        _report_sweep(known)


def cmd_thresholds(args) -> None:
    labels = read_annotations(args.annotations, args.unclear)
    judged = {k: v for k, v in labels.items() if v != args.unclear}
    records = read_run(args.run)
    randoms = read_key(args.key)
    known, left_out = estimate(records, judged, randoms)
    if not known:
        raise SystemExit("No records with a known label.")
    total = sum(r.weight for r in records)
    print(f"Estimated over the whole run ({len(records)} records):")
    if not randoms:
        print("  Without a key, agreements count as correct, so this is optimistic")
    if left_out:
        print(
            f"  {share(left_out, total)} of records are disagreements of a kind "
            "nobody annotated, left out"
        )
    _report_thresholds(known)
    random_known: Known = [
        (r, judged[r.id], r.weight)
        for r in records
        if r.id in randoms and r.id in judged
    ]
    if random_known:
        print(f"\nOn the random sample alone ({len(random_known)} records):")
        _report_thresholds(random_known)


def _definition(spec: object) -> object:
    if not isinstance(spec, dict) or not spec:
        return None
    if list(spec) == ["description"]:
        return spec["description"]
    return spec


def make_questions(scheme: dict, mode: str, instructions: str) -> dict:
    """Jev's questions, built as the `textcat_jev` action builds them."""
    if mode == "choice":
        return {
            "label": {
                "type": "choice",
                "instructions": instructions or "Which label applies to this text?",
                "criteria": {name: _definition(spec) for name, spec in scheme.items()},
            }
        }
    questions = {}
    for i, (name, spec) in enumerate(scheme.items()):
        ask = f"Does the label '{name}' apply to this text?"
        question: dict = {
            "type": "noul",
            "instructions": f"{instructions}\n\n{ask}" if instructions else ask,
        }
        definition = _definition(spec)
        if definition is not None:
            question["criteria"] = {"true": definition}
        questions[f"label_{i}"] = question
    return questions


def cmd_config(args) -> None:
    scheme = json.loads(args.labels.read_text(encoding="utf-8"))
    if isinstance(scheme, list):
        scheme = {name: {} for name in scheme}
    if len(scheme) == 1:
        mode = "binary"
    else:
        mode = "choice" if args.exclusive else "multi"
    instructions = args.instructions.read_text(encoding="utf-8").strip()
    thresholds = {}
    for spec in args.threshold:
        name, value = spec.split("=", 1)
        if name not in scheme:
            raise SystemExit(f"Unknown label in --threshold: {name}")
        thresholds[name] = float(value)
    models = Counter(r.model for r in read_run(args.run))
    model = models.most_common(1)[0][0]
    if mode == "choice":
        rule = (
            "Take answers.label.choice. When answers.label.confidence is below "
            "the chosen label's threshold, use your fallback instead."
        )
    else:
        rule = (
            "Apply labels[i] when answers.label_<i>.noul is at least its "
            "threshold, or 0.5 when it has none."
        )
    questions = make_questions(scheme, mode, instructions)
    config = {
        "endpoint": ENDPOINT,
        "model": model,
        "mode": mode,
        "labels": list(scheme),
        "questions": questions,
        "thresholds": thresholds,
        "decision": rule,
        "request": "POST {endpoint} with {model, state: <text>, questions}",
    }
    args.out.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote the {mode} configuration for {model} to {args.out}")


def cmd_drift(args) -> None:
    runs = [(p.name, read_run(p)) for p in (args.before, args.after)]
    totals = [sum(r.weight for r in records) for _, records in runs]
    names = sorted({r.jev for _, records in runs for r in records})
    print(f"Before: {runs[0][0]} ({len(runs[0][1])} records)")
    print(f"After: {runs[1][0]} ({len(runs[1][1])} records)")
    print(f"\n{'':<24}{'before':>24}{'after':>24}")
    print("Jev's labels")
    for label in names:
        cells = [
            share(sum(r.weight for r in records if r.jev == label), total)
            for (_, records), total in zip(runs, totals)
        ]
        print(f"  {label:<22}" + "".join(f"{c:>24}" for c in cells))
    print("Jev's confidence")
    for lo, hi in BANDS:
        cells = [
            share(sum(r.weight for r in records if lo <= r.confidence < hi), total)
            for (_, records), total in zip(runs, totals)
        ]
        band = f"{lo:.2f}-{min(hi, 1.0):.2f}"
        print(f"  {band:<22}" + "".join(f"{c:>24}" for c in cells))


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--unclear", default="UNCLEAR", help="the UNCLEAR label")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("labels", help="annotation label scheme")
    p.add_argument("scheme", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_labels)

    p = sub.add_parser("agreement", help="agreement with the LLM")
    p.add_argument("run", type=Path)
    p.set_defaults(func=cmd_agreement)

    p = sub.add_parser("sample", help="blind annotation sample")
    p.add_argument("run", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--disagreements", type=int, default=150)
    p.add_argument("--random", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("adjudicated", help="score runs against annotations")
    p.add_argument("annotations", type=Path)
    p.add_argument("runs", nargs="+", help="<name>=<run.jsonl>")
    p.add_argument("--key", type=Path)
    p.add_argument("--show", type=int, default=0)
    p.set_defaults(func=cmd_adjudicated)

    p = sub.add_parser("thresholds", help="accuracy at each threshold")
    p.add_argument("annotations", type=Path)
    p.add_argument("run", type=Path)
    p.add_argument("--key", type=Path)
    p.set_defaults(func=cmd_thresholds)

    p = sub.add_parser("config", help="export the configuration")
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--instructions", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--exclusive", action="store_true")
    p.add_argument("--threshold", action="append", default=[], help="LABEL=VALUE")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("drift", help="compare Jev on new records with a run")
    p.add_argument("before", type=Path)
    p.add_argument("after", type=Path)
    p.set_defaults(func=cmd_drift)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

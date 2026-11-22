"""Score every labeller of every component against gold labels, and the finished graph.

Run it from the template directory on files exported with `ellf datasets export` and the
assets the actions wrote (`ellf files cp`). It needs only the standard library: it reads
the template's own recipe package from `recipes/kg_recipes` without installing it.

The gold labels are always the gold datasets, however they were made: settled by the
evaluation reviews, or filled from a Gold labels asset by import-gold, link-candidates-eval
--gold-links and make-pairs-eval --gold-relations, which write them in the same shape.

    python scripts/score.py mentions --gold mentions-gold.jsonl --answers mentions-eval.jsonl
    python scripts/score.py linking --groups mention-groups-eval.jsonl --gold links-gold.jsonl [--answers links-eval.jsonl]
    python scripts/score.py relations --schema config/graph_schema.json --pairs pairs-eval.jsonl --gold relations-gold.jsonl --answers relations-eval.jsonl
    python scripts/score.py links --answers link-check.jsonl
    python scripts/score.py compare --graph graph-eval.jsonl --gold-graph graph-gold.jsonl
    python scripts/score.py questions --questions config/questions.json --answers answers/

Every command adds its figures to `scores.json` (or `--out`), which the service shows beside
the answers. Proportions come with a 95% Wilson interval: roughly 100 examples tell 80%
from 90%; telling 90% from 91% needs about 1,000.
"""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "recipes" / "kg_recipes"))

from kg_recipes import linking  # noqa: E402
from kg_recipes import schema as kg_schema  # noqa: E402
from kg_recipes.data import actor, flatten, read_jsonl  # noqa: E402
from kg_recipes.gold import relation_key  # noqa: E402

NONE = "NONE"
#: How a candidate was found, from the most to the least direct: see kg_recipes/linking.py.
MATCH_ORDER = {"name": 0, "alias": 1, "llm": 2, "approximate": 3, "broader": 4}


def interval(k: int, n: int, z: float = 1.96) -> Tuple[Optional[float], float, float]:
    """The proportion k/n with its 95% Wilson interval."""
    if n == 0:
        return None, 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, max(0.0, centre - half), min(1.0, centre + half)


def fmt(k: int, n: int) -> str:
    p, low, high = interval(k, n)
    return "–" if p is None else f"{p:6.1%} ({low:.0%}–{high:.0%}, n={n})"


def figure(k: int, n: int) -> dict:
    p, low, high = interval(k, n)
    return {"value": p, "low": low, "high": high, "n": n}


def answers(path: str) -> List[Tuple[dict, str]]:
    out = []
    for row in read_jsonl(Path(path)):
        eg = flatten(row)
        out.append((eg, actor(eg.get("_annotator_id") or eg.get("_session_id")) or "unknown"))
    return out


def save(out: str, section: str, data: dict) -> None:
    path = Path(out)
    scores = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if section in ("graph_links", "graph_vs_gold"):
        scores.setdefault("graph", {}).setdefault("links", {})
        for label, figures in data.items():
            scores["graph"]["links"].setdefault(label, {}).update(figures)
        if section == "graph_vs_gold":
            scores.setdefault("components", {})[section] = data
    else:
        scores.setdefault("components", {})[section] = data
    path.write_text(json.dumps(scores, indent=2), encoding="utf-8")
    print(f"\nSaved to {path}")


def mention_keys(eg: dict) -> Set[Tuple]:
    pid = (eg.get("meta") or {}).get("passage_id", "")
    return {(pid, int(s["start"]), int(s["end"]), s["label"]) for s in eg.get("spans") or []}


def cmd_mentions(args) -> None:
    gold: Set[Tuple] = set()
    gold_passages: Set[str] = set()
    for eg, _ in answers(args.gold):
        if eg.get("answer") == "accept":
            gold |= mention_keys(eg)
            gold_passages.add(eg["meta"]["passage_id"])
    found: Dict[str, Set[Tuple]] = defaultdict(set)
    answered: Dict[str, Set[str]] = defaultdict(set)
    for eg, who in answers(args.answers):
        pid = eg.get("meta", {}).get("passage_id")
        if eg.get("answer") == "accept" and pid in gold_passages:
            found[who] |= mention_keys(eg)
            answered[who].add(pid)
    types = sorted({k[3] for k in gold})
    result = {}
    print(f"Mentions: {len(gold)} gold mentions in {len(gold_passages)} passages\n")
    for who, keys in sorted(found.items()):
        result[who] = {"passages": len(answered[who])}
        # Each labeller is scored on the passages it answered: one that stopped early
        # isn't charged with the mentions in passages it never saw.
        print(f"{who}  ({len(answered[who])} passages)")
        for t in types:
            g = {k for k in gold if k[3] == t and k[0] in answered[who]}
            f = {k for k in keys if k[3] == t}
            hit = len(g & f)
            result[who][t] = {"precision": figure(hit, len(f)), "recall": figure(hit, len(g))}
            print(f"  {t:30} precision {fmt(hit, len(f))}   recall {fmt(hit, len(g))}")
    save(args.out, "mentions", result)


def gold_links(groups: List[dict], path: str) -> Tuple[Dict[str, List[Set[str]]], Set[str]]:
    """Each group's gold entries, one set per mention, from an export of the gold links
    dataset, and the groups whose gold answers were flagged.

    An answer about one mention (a second-round question, or a gold labels asset where a
    name has different entries in a document) overrides its group's for that mention. A
    group with no gold answer isn't scored.
    """
    rows = answers(path)
    by_group = {gid: set(ids) for gid, (ids, how) in linking.resolve(groups, rows).items() if how == "answers"}
    by_mention = linking.mention_answers(rows)
    flagged = {(eg.get("meta") or {}).get("group_id") for eg, _ in rows if eg.get("flagged")}
    out = {}
    for g in groups:
        if g["group_id"] not in by_group:
            continue
        out[g["group_id"]] = [set(by_mention.get((str(p), int(s), int(e)), by_group[g["group_id"]])) for p, s, e in g["mentions"]]
    return out, flagged


def cmd_linking(args) -> None:
    groups = list(read_jsonl(Path(args.groups)))
    gold, flagged = gold_links(groups, args.gold)
    said: Dict[str, Dict[str, Dict[str, bool]]] = defaultdict(lambda: defaultdict(dict))  # who -> group -> candidate -> yes
    if args.answers:
        for eg, who in answers(args.answers):
            meta = eg.get("meta") or {}
            if eg.get("answer") in ("accept", "reject") and meta.get("group_id") and not meta.get("mention_key"):
                said[who][meta["group_id"]][meta["candidate_id"]] = eg["answer"] == "accept"
    per_type: Dict[str, Counter] = defaultdict(Counter)
    found_by: Dict[str, Counter] = defaultdict(Counter)
    missed: Dict[str, List[dict]] = defaultdict(list)
    errors: Dict[str, Counter] = defaultdict(Counter)
    labellers: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for g in groups:
        golds = gold.get(g["group_id"])
        if not golds:
            continue
        right = set().union(*golds)
        t = g["type"]
        cands = {c["id"] for c in g["candidates"]}
        c = per_type[t]
        c["groups"] += 1
        c["names with different entries per mention"] += len({frozenset(x) for x in golds}) > 1
        if not right:
            c["gold NIL"] += 1
            # A reviewer who knows the right entry, but finds it among no candidate, flags it.
            c["gold NIL, flagged"] += g["group_id"] in flagged
        else:
            c["entry exists"] += 1
            c["right entry among candidates"] += bool(right & cands)
            matches = [x["match"] for x in g["candidates"] if x["id"] in right]
            if matches:
                found_by[t][min(matches, key=MATCH_ORDER.get)] += 1
            elif len(missed[t]) < 25:
                missed[t].append({"text": g["text"], "gold": sorted(right), "candidates": [x["name"] for x in g["candidates"][:3]]})
        if g.get("rule_ids"):
            ids = set(g["rule_ids"])
            c["linked by rule"] += 1
            c["rule right"] += ids == right
            if ids != right:
                errors[t][classify(ids, right, cands)] += 1
        elif g.get("rule_ids") == []:
            c["no candidate"] += 1
            c["no candidate, gold NIL"] += not right
            if right:
                errors[t]["right entry not a candidate"] += 1
        for who, by_group in said.items():
            if g["group_id"] in by_group:
                ids = {cid for cid, yes in by_group[g["group_id"]].items() if yes}
                lc = labellers[who][t]
                lc["groups"] += 1
                lc["right"] += ids == right
                lc["right entry among candidates"] += bool(right & cands) or not right
                lc["right when it was a candidate"] += ids == right and (bool(right & cands) or not right)
                lc["NIL answered"] += not ids
                lc["NIL answered and right"] += not ids and not right
                lc["gold NIL"] += not right
                if ids != right:
                    errors[t][classify(ids, right, cands)] += 1
    result = {}
    print("Entity linking\n")
    for t, c in sorted(per_type.items()):
        print(t)
        print(f"  mention groups with gold links {c['groups']}, gold NIL {c['gold NIL']}, of which flagged {c['gold NIL, flagged']}")
        print(f"  candidate recall (the ceiling)  {fmt(c['right entry among candidates'], c['entry exists'])}")
        print(f"  linked by rule                  {c['linked by rule']}, right {fmt(c['rule right'], c['linked by rule'])}")
        print(f"  no candidate, so NIL            {c['no candidate']}, of which gold is NIL {c['no candidate, gold NIL']}")
        print("  right entry found by            " + (", ".join(f"{k} {v}" for k, v in sorted(found_by[t].items(), key=lambda kv: MATCH_ORDER.get(kv[0], 9))) or "-"))
        print(f"  names with different entries per mention  {c['names with different entries per mention']}")
        result[t] = {
            "candidate_recall": figure(c["right entry among candidates"], c["entry exists"]),
            "rule_accuracy": figure(c["rule right"], c["linked by rule"]),
            "no_candidate": c["no candidate"],
            "no_candidate_gold_nil": c["no candidate, gold NIL"],
            "gold_nil_flagged": c["gold NIL, flagged"],
            "right_entry_found_by": dict(found_by[t]),
            "names_with_different_entries_per_mention": c["names with different entries per mention"],
            "missed": missed[t],
            "labellers": {},
            "errors": dict(errors[t]),
        }
        for who, by_type in sorted(labellers.items()):
            lc = by_type.get(t)
            if not lc:
                continue
            print(
                f"  {who:30} accuracy {fmt(lc['right'], lc['groups'])}   when the right entry was a candidate "
                f"{fmt(lc['right when it was a candidate'], lc['right entry among candidates'])}   "
                f"NIL precision {fmt(lc['NIL answered and right'], lc['NIL answered'])}   NIL recall {fmt(lc['NIL answered and right'], lc['gold NIL'])}"
            )
            result[t]["labellers"][who] = {
                "accuracy": figure(lc["right"], lc["groups"]),
                "accuracy_when_candidate": figure(lc["right when it was a candidate"], lc["right entry among candidates"]),
                "nil_precision": figure(lc["NIL answered and right"], lc["NIL answered"]),
                "nil_recall": figure(lc["NIL answered and right"], lc["gold NIL"]),
            }
        if errors[t]:
            print("  errors: " + ", ".join(f"{k} {v}" for k, v in errors[t].most_common()))
    print(
        "\nCandidate recall counts the right entries the gold has. Gold settled in the reviews can only"
        "\nsay yes to a candidate, so a name whose right entry no source found is NIL there, unless the"
        "\nreviewer flagged it: read the flagged ones before trusting the NIL figures. A Gold labels asset"
        "\nhas every right entry. Groups with no candidate have no questions, so they're only scored with"
        "\na Gold labels asset; ask about the rule's groups too with link-candidates-eval --ask-all."
    )
    save(args.out, "linking", result)


def classify(ids: Set[str], right: Set[str], cands: Set[str]) -> str:
    if right and not (right & cands):
        return "right entry not a candidate"
    if ids and not right:
        return "linked, gold is NIL"
    if not ids and right:
        return "wrongly NIL"
    return "wrong entry"


def pair_key(meta: dict, schema) -> Tuple:
    group = schema.relation(meta["group"])
    where = meta["doc_id"] if group.scope == "document" else meta["passage_id"]
    return relation_key(group.name, where, meta["head_id"], meta["tail_id"], group.directed)


def labels_of(eg: dict) -> Optional[Set[str]]:
    """The labels an accepted answer chose, NONE left out (empty: the answer is NONE)."""
    if eg.get("answer") != "accept" or not eg.get("accept"):
        return None
    return {l for l in eg["accept"] if l != NONE}


def gold_by_pair(path: str, pairs: Dict[str, Tuple]) -> Tuple[Dict[Tuple, Set[str]], int]:
    """Gold labels by relation key from an export of the gold relations dataset (NONE left
    out), and how many pairs it answers."""
    out, answered = {}, 0
    for eg, _ in answers(path):
        pid = (eg.get("meta") or {}).get("pair_id")
        labels = labels_of(eg)
        if pid in pairs and labels is not None:
            answered += 1
            if labels:
                out[pairs[pid]] = labels
    return out, answered


def cmd_relations(args) -> None:
    schema = kg_schema.load(args.schema)
    pairs = {r["meta"]["pair_id"]: pair_key(r["meta"], schema) for r in read_jsonl(Path(args.pairs))}
    gold, answered = gold_by_pair(args.gold, pairs)
    if not answered:
        sys.exit(f"No gold answers in {args.gold} for the pairs in {args.pairs}: is it an export of the gold relations dataset of these pairs?")
    print(f"Relations: {len(pairs)} pairs, {answered} with a gold answer, {len(gold)} gold relations\n")
    by_who: Dict[str, Dict[Tuple, Set[str]]] = defaultdict(dict)
    for eg, who in answers(args.answers):
        pid = (eg.get("meta") or {}).get("pair_id")
        labels = labels_of(eg)
        if pid in pairs and labels is not None:
            by_who[who][pairs[pid]] = labels
    result = {}
    for who, said in sorted(by_who.items()):
        right = sum(1 for k, ls in said.items() if gold.get(k, set()) == ls)
        print(f"{who}: accuracy {fmt(right, len(said))} (every label of the pair right)")
        result[who] = {"accuracy": figure(right, len(said)), "labels": {}}
        labels = sorted(set().union(*gold.values(), *said.values()))
        for label in labels:
            given = [k for k, ls in said.items() if label in ls]
            true = [k for k in said if label in gold.get(k, set())]
            hit = sum(1 for k in given if label in gold.get(k, set()))
            print(f"  {label:28} precision {fmt(hit, len(given))}   recall {fmt(hit, len(true))}")
            result[who]["labels"][label] = {"precision": figure(hit, len(given)), "recall": figure(hit, len(true))}
        wrong = sum(1 for k, ls in said.items() if ls and not gold.get(k))
        missed = sum(1 for k, ls in said.items() if not ls and gold.get(k))
        print(f"  links made where gold has none: {wrong}; gold links answered NONE: {missed}")
        result[who]["wrong_links"], result[who]["missed_links"] = wrong, missed
    save(args.out, "relations", result)


def cmd_links(args) -> None:
    by_label: Dict[str, Counter] = defaultdict(Counter)
    for eg, _ in answers(args.answers):
        meta = eg.get("meta") or {}
        if eg.get("answer") in ("accept", "reject") and meta.get("label"):
            by_label[meta["label"]]["checked"] += 1
            by_label[meta["label"]]["correct"] += eg["answer"] == "accept"
    result = {}
    print("Precision of the graph's links, from the checked sample\n")
    for label, c in sorted(by_label.items()):
        p, low, high = interval(c["correct"], c["checked"])
        print(f"  {label:28} {fmt(c['correct'], c['checked'])}")
        result[label] = {"precision": p, "low": low, "high": high, "checked": c["checked"]}
    save(args.out, "graph_links", result)


def graph_links(path: str) -> Dict[str, Set[Tuple[str, str]]]:
    """Each label's links in a graph export, as (head, tail)."""
    out: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for row in read_jsonl(Path(path)):
        if row.get("kind") == "link":
            out[row["label"]].add((row["head"], row["tail"]))
    return out


def cmd_compare(args) -> None:
    built, gold = graph_links(args.graph), graph_links(args.gold_graph)
    result = {}
    print("Links of the graph against the gold graph on the same documents\n")
    for label in sorted(set(built) | set(gold)):
        hit = len(built[label] & gold[label])
        print(f"  {label:28} precision {fmt(hit, len(built[label]))}   recall {fmt(hit, len(gold[label]))}")
        p, low, high = interval(hit, len(gold[label]))
        # The recall goes beside the link check's precision, which the service shows with
        # the questions; this precision is on the evaluation documents only, so it's kept apart.
        result[label] = {
            "recall": p, "recall_low": low, "recall_high": high, "recall_n": len(gold[label]),
            "precision_on_eval": figure(hit, len(built[label])),
        }
    save(args.out, "graph_vs_gold", result)


def cmd_questions(args) -> None:
    """Each question's answer against the expected rows written in the questions file.

    A question's "expected" is a list of rows, each with some of the answer's columns,
    e.g. [{"entity": "Acme Corporation"}]; rows match on those columns, ignoring case. The answers
    are the service's `api/questions/<name>` responses, saved as <name>.json.
    """
    norm = lambda v: v.strip().lower() if isinstance(v, str) else v
    result = {}
    for q in json.loads(Path(args.questions).read_text(encoding="utf-8")):
        expected = q.get("expected")
        path = Path(args.answers) / f"{q['name']}.json"
        if not expected:
            print(f"{q['name']}: no expected answer written")
            continue
        if not path.exists():
            print(f"{q['name']}: no saved answer at {path}")
            continue
        cols = sorted({c for row in expected for c in row})
        want = {tuple(norm(row.get(c)) for c in cols) for row in expected}
        got = {tuple(norm(row.get(c)) for c in cols) for row in json.loads(path.read_text(encoding="utf-8")).get("rows", [])}
        hit = want & got
        print(f"{q['name']}: precision {fmt(len(hit), len(got))}   recall {fmt(len(hit), len(want))}")
        for label, rows in (("missing", want - got), ("not expected", got - want)):
            for row in sorted(rows, key=str)[: args.show]:
                print(f"  {label}: " + ", ".join(f"{c}={v}" for c, v in zip(cols, row)))
        result[q["name"]] = {"precision": figure(len(hit), len(got)), "recall": figure(len(hit), len(want))}
    save(args.out, "questions", result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="scores.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("mentions", help="each labeller's mentions against the gold mentions")
    p.add_argument("--gold", required=True, help="export of the mentions gold dataset")
    p.add_argument("--answers", required=True, help="export of the mentions dataset of the evaluation documents")
    p = sub.add_parser("linking", help="candidate recall, the rule and each labeller against the gold links")
    p.add_argument("--groups", required=True, help="the mention groups asset of the evaluation documents")
    p.add_argument("--gold", required=True, help="export of the gold links dataset")
    p.add_argument("--answers", help="export of the links dataset of the evaluation questions")
    p = sub.add_parser("relations", help="each labeller's relation labels against the gold relations")
    p.add_argument("--schema", required=True)
    p.add_argument("--pairs", required=True, help="the pairs asset of the evaluation documents")
    p.add_argument("--gold", required=True, help="export of the relation group's gold dataset")
    p.add_argument("--answers", required=True, help="export of the relations dataset of the evaluation pairs")
    p = sub.add_parser("links", help="precision of the graph's links from the link-check task")
    p.add_argument("--answers", required=True, help="export of the link-check dataset")
    p = sub.add_parser("compare", help="a graph's links against the gold graph on the same documents: the graph's recall")
    p.add_argument("--graph", required=True, help="a graph export, e.g. from build_graph.py")
    p.add_argument("--gold-graph", required=True, help="the gold graph's export")
    p = sub.add_parser("questions", help="each question's answer against its expected rows")
    p.add_argument("--questions", required=True, help="config/questions.json, with expected answers")
    p.add_argument("--answers", required=True, help="a folder of the service's api/questions/<name> responses, as <name>.json")
    p.add_argument("--show", type=int, default=10, help="how many missing and unexpected rows to list per question")
    args = parser.parse_args()
    {"mentions": cmd_mentions, "linking": cmd_linking, "relations": cmd_relations, "links": cmd_links, "compare": cmd_compare, "questions": cmd_questions}[args.cmd](args)


if __name__ == "__main__":
    main()

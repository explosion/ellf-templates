"""Build the graph locally from exported datasets, the way the knowledge-graph service builds
it, and write it in the format of the service's `api/export`.

Use it for the graphs the service isn't created for: the graph the labellers' answers
make on the evaluation documents, and the gold graph with one component's gold swapped
for a labeller's answers. `score.py compare` then measures either against the gold graph.
It needs only Python's standard library.

    python scripts/build_graph.py --schema config/graph_schema.json --entity-list entity_list.jsonl \\
        --documents documents-eval.jsonl --groups mention-groups-eval.jsonl \\
        --mentions mentions-gold.jsonl --links links-gold.jsonl \\
        --relations relations-<group>-eval.jsonl:<labeller> --out graph-relations-<labeller>.jsonl

--documents, --groups and --entity-list are the assets (`ellf files cp`); --mentions,
--links and --relations are `ellf datasets export` files, each repeatable. Add
`:<labeller>` to an export to keep only that labeller's answers, by the name the scores
show for it.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "recipes" / "kg_recipes"))

from kg_recipes import graph  # noqa: E402
from kg_recipes import schema as kg_schema  # noqa: E402
from kg_recipes.data import EXPORTS_ENV, actor, flatten, read_jsonl  # noqa: E402


def stage(spec: str, out_dir: Path, n: int) -> str:
    """Copy an export, or one labeller's answers in it, to where the graph code reads
    datasets from; returns the name to read it by."""
    path, _, who = spec.partition(":") if not Path(spec).exists() else (spec, "", "")
    name = f"{n}-{Path(path).stem}"
    with open(out_dir / f"{name}.jsonl", "w", encoding="utf-8") as f:
        for row in read_jsonl(Path(path)):
            flat = flatten(row)
            if who and actor(flat.get("_annotator_id") or flat.get("_session_id")) != who:
                continue
            f.write(json.dumps(row) + "\n")
    return name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--entity-list", required=True)
    parser.add_argument("--documents", action="append", required=True)
    parser.add_argument("--groups", action="append", required=True)
    parser.add_argument("--mentions", action="append", required=True)
    parser.add_argument("--links", action="append", default=[])
    parser.add_argument("--relations", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[EXPORTS_ENV] = tmp
        names = {k: [stage(s, Path(tmp), i) for i, s in enumerate(getattr(args, k))] for k in ("mentions", "links", "relations")}
        rows = graph.assemble(
            graph.Sources(
                schema=kg_schema.load(args.schema),
                documents=args.documents,
                entity_list=args.entity_list,
                groups=args.groups,
                mentions=names["mentions"],
                links=names["links"],
                relations=names["relations"],
            )
        )
    with open(args.out, "w", encoding="utf-8") as f:
        for e in rows.entities:
            f.write(json.dumps({"kind": "entity", **e}) + "\n")
        for link in rows.links:
            f.write(json.dumps({"kind": "link", **{k: v for k, v in link.items() if k != "ends"}}) + "\n")
    print(f"{rows.summary()}. Wrote {args.out}.")


if __name__ == "__main__":
    main()

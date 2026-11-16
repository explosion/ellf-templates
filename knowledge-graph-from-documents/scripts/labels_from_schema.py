"""Write the label schemes of the mentions and relation tasks from the graph schema.

    python scripts/labels_from_schema.py config/graph_schema.json assets/

Writes assets/mention_labels.json (one label per entity type) and, for every relation
group, assets/relation_labels_<group>.json (its labels and NONE). Publish them with
`ellf publish data ... --kind labels`; run it again and publish a new version whenever
the schema's types or labels change.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "recipes" / "kg_recipes"))

from kg_recipes import schema as kg_schema  # noqa: E402

NONE_ENTRY = {
    "description": (
        "The passage states none of these relations between the two marked entities, "
        "including when it only mentions them together, or says the relation doesn't hold."
    )
}


def main(schema_path: str, out_dir: str) -> None:
    graph = kg_schema.load(schema_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mentions = {name: t.scheme for name, t in graph.entity_types.items()}
    (out / "mention_labels.json").write_text(json.dumps(mentions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out / 'mention_labels.json'}: {', '.join(mentions)}")
    for group in graph.relations:
        labels = {**group.labels, kg_schema.NONE: NONE_ENTRY}
        path = out / f"relation_labels_{group.name.lower()}.json"
        path.write_text(json.dumps(labels, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {path}: {', '.join(labels)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])

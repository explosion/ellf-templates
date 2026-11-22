"""The graph schema: the one file that says what the graph holds.

    {
      "entity_types": {
        "<TYPE>": {
          "description": "What counts as a mention of this type.",
          "do_not_mark": [],       # look-alikes, as in a label scheme; also "examples"
          "linked": true,          # linked to entries of this type in the entity list
          "level": "...",          # which level of the list an entry is, in words
          "multiple": false,       # may one mention link to several entries?
          "nil": "node",           # a mention with no entry: "node" or "drop"
          "max_candidates": 5,
          "ignore_words": []       # words dropped when matching names, e.g. forms or suffixes
        }
      },
      "relations": [
        {
          "name": "<group>",       # one labelling task per group
          "head": ["<TYPE>"], "tail": ["<TYPE>"],
          "labels": {"<LABEL>": {"description": "What the passage must state.", "do_not_mark": [], "examples": []}},
          "directed": true,
          "exclusive": true,       # one label per pair; false when a passage can state several
          "scope": "passage",      # or "document": pairs anywhere in a document
          "conditions": {"<NAME>": "<regular expression>"},
          "combine": "any"         # "any", "latest" or "majority"
        }
      ],
      "checks": [
        {"name": "...", "description": "...", "cypher": "MATCH ... RETURN ..."}
      ]
    }

NONE is added to every relation group's labels: the passage states none of them. A
label's value can also be just its description. ``scripts/labels_from_schema.py`` writes
the label schemes of the mentions and relation tasks from this file.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

NONE = "NONE"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
COMBINE = ("any", "latest", "majority")
SCOPES = ("passage", "document")
NIL_RULES = ("node", "drop")


class SchemaError(ValueError):
    pass


@dataclass
class EntityType:
    name: str
    description: str = ""
    linked: bool = True
    level: str = ""
    multiple: bool = False
    nil: str = "node"
    max_candidates: int = 5
    ignore_words: List[str] = field(default_factory=list)
    scheme: Dict = field(default_factory=dict)


@dataclass
class RelationGroup:
    name: str
    head: List[str]
    tail: List[str]
    labels: Dict[str, dict]
    directed: bool = True
    exclusive: bool = True
    scope: str = "passage"
    conditions: Dict[str, str] = field(default_factory=dict)
    combine: str = "any"

    @property
    def all_labels(self) -> List[str]:
        return [*self.labels, NONE]

    def allows(self, head_type: str, tail_type: str) -> bool:
        if head_type in self.head and tail_type in self.tail:
            return True
        return not self.directed and head_type in self.tail and tail_type in self.head

    def condition_patterns(self) -> Dict[str, "re.Pattern[str]"]:
        return {name: re.compile(pattern, re.IGNORECASE) for name, pattern in self.conditions.items()}


@dataclass
class Check:
    name: str
    cypher: str
    description: str = ""


@dataclass
class Schema:
    entity_types: Dict[str, EntityType]
    relations: List[RelationGroup]
    checks: List[Check] = field(default_factory=list)

    def relation(self, name: str) -> RelationGroup:
        for group in self.relations:
            if group.name == name:
                return group
        raise SchemaError(f"No relation group named {name!r}; the schema has {', '.join(g.name for g in self.relations)}")

    def relation_for_label(self, label: str) -> Optional[RelationGroup]:
        for group in self.relations:
            if label in group.labels:
                return group
        return None


SCHEME_KEYS = ("description", "do_not_mark", "examples")


def scheme_entry(spec) -> dict:
    """The label-scheme part of an entity type or label: description, do_not_mark, examples."""
    if not isinstance(spec, dict):
        return {"description": str(spec)} if spec else {}
    return {k: spec[k] for k in SCHEME_KEYS if spec.get(k)}


def _name(value: str, what: str) -> str:
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise SchemaError(f"{what} {value!r} must start with a letter and use only letters, digits and _")
    return value


def parse(data: dict) -> Schema:
    """A schema from its JSON. Raises SchemaError with every reason it can't be used."""
    if not isinstance(data, dict):
        raise SchemaError("The schema must be a JSON object")
    raw_types = data.get("entity_types") or {}
    if not raw_types:
        raise SchemaError("The schema needs at least one entity type under 'entity_types'")
    types: Dict[str, EntityType] = {}
    for name, spec in raw_types.items():
        _name(name, "Entity type")
        spec = spec or {}
        nil = spec.get("nil", "node")
        if nil not in NIL_RULES:
            raise SchemaError(f"Entity type {name}: 'nil' must be one of {', '.join(NIL_RULES)}")
        types[name] = EntityType(
            name=name,
            description=str(spec.get("description", "")),
            linked=bool(spec.get("linked", True)),
            level=str(spec.get("level", "")),
            multiple=bool(spec.get("multiple", False)),
            nil=nil,
            max_candidates=int(spec.get("max_candidates", 5)),
            ignore_words=[str(w).lower() for w in spec.get("ignore_words") or []],
            scheme=scheme_entry(spec),
        )
    groups: List[RelationGroup] = []
    seen_labels: Dict[str, str] = {}
    for spec in data.get("relations") or []:
        name = _name(spec.get("name", ""), "Relation group")
        if any(g.name == name for g in groups):
            raise SchemaError(f"Two relation groups are named {name}")
        head, tail = list(spec.get("head") or []), list(spec.get("tail") or [])
        for t in head + tail:
            if t not in types:
                raise SchemaError(f"Relation group {name} names entity type {t!r}, which the schema doesn't define")
        if not head or not tail:
            raise SchemaError(f"Relation group {name} needs entity types under 'head' and 'tail'")
        labels = spec.get("labels") or {}
        if isinstance(labels, list):
            labels = {label: "" for label in labels}
        if not labels:
            raise SchemaError(f"Relation group {name} needs at least one label")
        for label in labels:
            _name(label, f"Label in {name}")
            if label == NONE:
                raise SchemaError(f"Relation group {name}: NONE is added for you; leave it out of 'labels'")
            if label in seen_labels:
                raise SchemaError(f"Label {label} is in both {seen_labels[label]} and {name}; labels must be unique")
            seen_labels[label] = name
        scope = spec.get("scope", "passage")
        if scope not in SCOPES:
            raise SchemaError(f"Relation group {name}: 'scope' must be one of {', '.join(SCOPES)}")
        combine = spec.get("combine", "any")
        if combine not in COMBINE:
            raise SchemaError(f"Relation group {name}: 'combine' must be one of {', '.join(COMBINE)}")
        conditions = dict(spec.get("conditions") or {})
        for cond, pattern in conditions.items():
            _name(cond, f"Condition in {name}")
            try:
                re.compile(pattern)
            except re.error as err:
                raise SchemaError(f"Relation group {name}, condition {cond}: not a regular expression ({err})")
        groups.append(
            RelationGroup(
                name=name,
                head=head,
                tail=tail,
                labels={k: scheme_entry(v if isinstance(v, dict) else {"description": v}) for k, v in labels.items()},
                directed=bool(spec.get("directed", True)),
                exclusive=bool(spec.get("exclusive", True)),
                scope=scope,
                conditions=conditions,
                combine=combine,
            )
        )
    checks = []
    for spec in data.get("checks") or []:
        if not spec.get("name") or not spec.get("cypher"):
            raise SchemaError("Every check needs a 'name' and a 'cypher' query")
        checks.append(Check(name=spec["name"], cypher=spec["cypher"], description=spec.get("description", "")))
    return Schema(entity_types=types, relations=groups, checks=checks)


def load(source: Union[str, Path, dict]) -> Schema:
    """A schema from a dict, a JSON string, or the path of a JSON file."""
    if isinstance(source, dict):
        return parse(source)
    text = str(source)
    if text.lstrip().startswith("{"):
        return parse(json.loads(text))
    return parse(json.loads(Path(text).read_text(encoding="utf-8")))

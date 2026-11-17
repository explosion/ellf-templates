import pytest

from kg_recipes import documents, gold, graph, linking, pairs, schema
from kg_recipes.mentions import Mention, abbreviations

SCHEMA = {
    "entity_types": {
        "COMPANY": {"description": "A company.", "nil": "node"},
        "PRODUCT": {"description": "A product.", "nil": "drop", "ignore_words": ["inc"]},
        "PLACE": {"linked": False},
    },
    "relations": [
        {"name": "MAKES", "head": ["COMPANY"], "tail": ["PRODUCT"], "labels": {"MAKES": "", "SELLS": ""}, "exclusive": False, "conditions": {"PLANNED": "\\bwill\\b"}},
        {"name": "NEAR", "head": ["PLACE"], "tail": ["PLACE"], "labels": ["NEAR"], "directed": False, "scope": "document"},
    ],
    "checks": [{"name": "no self links", "cypher": "MATCH (a)-[r]->(a) RETURN a"}],
}
ENTRIES = [
    {"id": "C1", "type": "COMPANY", "name": "Acme Corporation", "aliases": ["Acme"], "description": "Makes everything."},
    {"id": "C2", "type": "COMPANY", "name": "Acme Labs"},
    {"id": "P1", "type": "PRODUCT", "name": "Rocket Skates"},
    {"id": "X1", "type": "OTHER", "name": "Ignored"},
]


@pytest.fixture
def graph_schema():
    return schema.parse(SCHEMA)


def test_schema_rejects_unknown_types_and_reserved_labels():
    bad = {**SCHEMA, "relations": [{"name": "R", "head": ["NOPE"], "tail": ["COMPANY"], "labels": ["X"]}]}
    with pytest.raises(schema.SchemaError, match="NOPE"):
        schema.parse(bad)
    bad = {**SCHEMA, "relations": [{"name": "R", "head": ["COMPANY"], "tail": ["PRODUCT"], "labels": ["NONE"]}]}
    with pytest.raises(schema.SchemaError, match="NONE"):
        schema.parse(bad)


def test_documents_split_by_document_and_stable():
    docs = [documents.parse_document({"doc_id": f"D{i}", "text": "One.\n\nTwo."}) for i in range(200)]
    label, held = documents.split(docs, 0.2)
    assert 20 < len(held) < 60 and len(label) + len(held) == 200
    more = docs + [documents.parse_document({"doc_id": "NEW", "text": "x"})]
    assert {d.doc_id for d in documents.split(more, 0.2)[1]} - {"NEW"} == {d.doc_id for d in held}


def test_whole_document_passage_joins_paragraphs():
    doc = documents.parse_document({"doc_id": "D", "text": "One.\n\nTwo."}, whole_document=True)
    rows = list(documents.passage_rows(doc))
    assert [r["meta"]["kind"] for r in rows] == ["paragraph", "paragraph", "document"]
    assert rows[2]["text"] == "One.\n\nTwo."
    with pytest.raises(ValueError):
        documents.parse_document({"text": "no id"})


def test_abbreviations():
    text = "The hepatocyte nuclear factor (HNF)-6 gene and transforming growth factor beta (TGF-beta) were tested."
    found = abbreviations(text)
    assert found["HNF"] == "hepatocyte nuclear factor"
    assert found["TGF-beta"] == "transforming growth factor beta"


def test_candidates_rule_and_questions(graph_schema, tmp_path):
    entities = linking.EntityList.from_rows(ENTRIES, graph_schema, str(tmp_path / "e.sqlite"))
    assert len(entities) == 3
    text = "Acme Corporation sells Rocket Skates. Acme will make more."
    passage = {"text": text, "meta": {"doc_id": "D", "passage_id": "D:0"}}
    mentions = [
        Mention("D", "D:0", 0, 16, "Acme Corporation", "COMPANY"),
        Mention("D", "D:0", 23, 36, "Rocket Skates", "PRODUCT"),
        Mention("D", "D:0", 38, 42, "Acme", "COMPANY"),
    ]
    groups = linking.mention_groups(mentions, graph_schema, {"D": text})
    linking.add_candidates(groups, entities, graph_schema)
    by_text = {g.text: g for g in groups}
    assert by_text["Acme Corporation"].rule_ids == ["C1"]
    assert by_text["Rocket Skates"].rule_ids == ["P1"]
    acme = by_text["Acme"]
    assert {c.id for c in acme.candidates} >= {"C1"}
    rows = linking.question_rows(groups, entities, {"D:0": passage})
    assert all(r["meta"]["group_id"] not in (by_text["Rocket Skates"].group_id,) for r in rows)
    for r in rows:
        s = r["spans"][0]
        assert r["text"][s["start"] : s["end"]] == r["meta"]["mention"]


def test_resolve_waits_for_answers():
    rows = [{"group_id": "g1", "rule_ids": None}, {"group_id": "g2", "rule_ids": ["A"]}, {"group_id": "g3", "rule_ids": None}]
    answers = [({"answer": "accept", "meta": {"group_id": "g1", "candidate_id": "B"}}, "x"), ({"answer": "reject", "meta": {"group_id": "g1", "candidate_id": "C"}}, "x")]
    resolved = linking.resolve(rows, answers)
    assert resolved == {"g1": (["B"], "answers"), "g2": (["A"], "rule")}


def test_pairs_and_graph(graph_schema):
    text = "Acme will sell Rocket Skates in Springfield near Shelbyville."
    passages = [{"text": text, "meta": {"doc_id": "D", "passage_id": "D:0", "kind": "paragraph", "doc_version": "1", "doc_date": "2024"}}]
    mentions = [
        Mention("D", "D:0", 0, 4, "Acme", "COMPANY"),
        Mention("D", "D:0", 15, 28, "Rocket Skates", "PRODUCT"),
        Mention("D", "D:0", 32, 43, "Springfield", "PLACE"),
    ]
    group_rows = [
        {"group_id": "a", "type": "COMPANY", "mentions": [["D:0", 0, 4]], "rule_ids": ["C1"]},
        {"group_id": "b", "type": "PRODUCT", "mentions": [["D:0", 15, 28]], "rule_ids": ["P1"]},
    ]
    resolved = linking.resolve(group_rows, [])
    nodes = pairs.mention_nodes(mentions, group_rows, resolved, graph_schema, {"C1": "Acme Corporation", "P1": "Rocket Skates"})
    rows = pairs.pair_rows(graph_schema.relation("MAKES"), {"D": passages}, mentions, nodes)
    assert len(rows) == 1
    row = rows[0]
    assert row["meta"]["head_id"] == "C1" and row["meta"]["conditions"] == ["PLANNED"]
    assert "[[Acme]]" in row["text"] and "{{Rocket Skates}}" in row["text"]
    for s in row["spans"]:
        assert row["text"][s["start"] : s["end"]] in ("Acme", "Rocket Skates")
    settled = [({**row, "answer": "accept", "accept": ["SELLS"]}, "reviewer")]
    built = graph.build(graph_schema, passages, mentions, nodes, settled)
    assert [(l["head"], l["label"], l["tail"]) for l in built.links] == [("C1", "SELLS", "P1")]
    assert built.links[0]["conditions"] == ["PLANNED"] and built.evidence[0]["settled_by"] == "reviewer"
    both = [({**row, "answer": "accept", "accept": ["MAKES", "SELLS"]}, "reviewer")]
    built = graph.build(graph_schema, passages, mentions, nodes, both)
    assert sorted(l["label"] for l in built.links) == ["MAKES", "SELLS"]
    none = [({**row, "answer": "accept", "accept": ["NONE"]}, "reviewer")]
    assert graph.build(graph_schema, passages, mentions, nodes, none).links == []


def test_nil_rules(graph_schema):
    mentions = [Mention("D", "D:0", 0, 4, "Zeta", "COMPANY"), Mention("D", "D:0", 5, 9, "Gizmo", "PRODUCT")]
    group_rows = [
        {"group_id": "a", "type": "COMPANY", "mentions": [["D:0", 0, 4]], "rule_ids": []},
        {"group_id": "b", "type": "PRODUCT", "mentions": [["D:0", 5, 9]], "rule_ids": []},
    ]
    nodes = pairs.mention_nodes(mentions, group_rows, linking.resolve(group_rows, []), graph_schema, {})
    assert nodes[mentions[0].key][0].id == "NIL:COMPANY:zeta"
    assert mentions[1].key not in nodes


def test_gold_relation_keys(graph_schema):
    rows = [{"doc_id": "D", "relations": [
        {"label": "NEAR", "head": "B", "tail": "A"},
        {"label": "MAKES", "head": "C1", "tail": "P1", "passage": 0},
        {"label": "SELLS", "head": "C1", "tail": "P1", "passage": 0},
    ]}]
    passages = {"D": [{"text": "x", "meta": {"passage_id": "D:0", "kind": "paragraph"}}]}
    found = gold.gold_relations(rows, passages, graph_schema)
    assert found[("NEAR", "D", "A", "B")] == {"NEAR"}
    assert found[("MAKES", "D:0", "C1", "P1")] == {"MAKES", "SELLS"}
    assert graph_schema.relation("MAKES").exclusive is False and graph_schema.relation("NEAR").exclusive is True


def test_token_aligned_widens_and_drops():
    import spacy

    from kg_recipes.mentions import token_aligned

    nlp = spacy.blank("en")
    text = "The IL6Ralpha gene is here."
    spans, widened, dropped = token_aligned(nlp, text, [{"start": 4, "end": 8, "label": "G"}, {"start": 3, "end": 4, "label": "G"}, {"start": 14, "end": 18, "label": "G"}])
    assert [text[s["start"] : s["end"]] for s in spans] == ["IL6Ralpha", "gene"]
    assert widened == 1 and dropped == 1


def test_question_parameters_are_typed():
    from kg_recipes.app import typed

    assert typed("5", 20) == 5 and typed("0.5", 0.1) == 0.5 and typed("true", False) is True and typed("x", "y") == "x"


BROADER_ENTRIES = [
    {"id": "D1", "type": "COMPANY", "name": "Holding Group"},
    {"id": "D2", "type": "COMPANY", "name": "Rocket Works", "aliases": ["Rocket Workshop"], "broader": ["D1"]},
    {"id": "D3", "type": "COMPANY", "name": "Rocket Labs"},
]


def test_optional_sources_only_without_an_exact_match(graph_schema, tmp_path):
    entities = linking.EntityList.from_rows(BROADER_ENTRIES, graph_schema, str(tmp_path / "e.sqlite"))
    text = "Rocket Works and the Rockets workshop and Zeta Corp."
    mentions = [
        Mention("D", "D:0", 0, 12, "Rocket Works", "COMPANY"),
        Mention("D", "D:0", 21, 37, "Rockets workshop", "COMPANY"),
        Mention("D", "D:0", 42, 51, "Zeta Corp", "COMPANY"),
    ]
    groups = linking.mention_groups(mentions, graph_schema, {"D": text})
    asked = []

    def propose(g, context):
        asked.append(g.text)
        return ["Rocket Labs"] if g.text == "Zeta Corp" else []

    contexts = {g.group_id: text for g in groups}
    linking.add_candidates(groups, entities, graph_schema, propose=propose, broader=True, contexts=contexts)
    by_text = {g.text: g for g in groups}
    assert by_text["Rocket Works"].rule_ids == ["D2"]
    assert "Rocket Works" not in asked
    workshop = {c.id: c.match for c in by_text["Rockets workshop"].candidates}
    assert workshop.get("D1") == "broader"
    assert {c.id: c.match for c in by_text["Zeta Corp"].candidates}["D3"] == "llm"


def test_fix_rows_retry_and_split(graph_schema, tmp_path):
    entities = linking.EntityList.from_rows(ENTRIES + BROADER_ENTRIES, graph_schema, str(tmp_path / "e.sqlite"))
    text = "Acme Labs sued Acme. Later Acme merged with Rocket Labs."
    passages = {"D:0": {"text": text, "meta": {"doc_id": "D", "passage_id": "D:0"}}}
    rows = [
        {"group_id": "acme", "doc_id": "D", "type": "COMPANY", "text": "Acme", "mentions": [["D:0", 15, 19], ["D:0", 27, 31]],
         "candidates": [{"id": "C1", "name": "Acme Corporation", "match": "alias", "score": 1.0}, {"id": "C2", "name": "Acme Labs", "match": "approximate", "score": 0.7}], "rule_ids": None},
        {"group_id": "rl", "doc_id": "D", "type": "COMPANY", "text": "Rocket Labs", "mentions": [["D:0", 44, 55]],
         "candidates": [{"id": "D2", "name": "Rocket Works", "match": "approximate", "score": 0.6}], "rule_ids": None},
    ]
    answers = [
        ({"answer": "accept", "meta": {"group_id": "acme", "candidate_id": "C1"}}, "a"),
        ({"answer": "accept", "meta": {"group_id": "acme", "candidate_id": "C2"}}, "a"),
        ({"answer": "reject", "meta": {"group_id": "rl", "candidate_id": "D2"}}, "a"),
    ]
    out, counts = linking.fix_rows(rows, answers, entities, graph_schema, passages, wider=5)
    assert counts["split"] == 1 and counts["retry"] == 1
    split = [r for r in out if r["meta"]["fix"] == "split"]
    assert len(split) == 4 and {tuple(r["meta"]["mention_key"]) for r in split} == {("D:0", 15, 19), ("D:0", 27, 31)}
    settled = answers + [({**r, "answer": "accept" if r["meta"]["candidate_id"] == "C1" else "reject"}, "a") for r in split]
    again, counts = linking.fix_rows(rows, settled, entities, graph_schema, passages, wider=5)
    assert counts["split"] == 0
    unlisted = [({"answer": "accept", "meta": {"group_id": "acme", "candidate_id": "GONE"}}, "a")]
    out_unlisted, counts = linking.fix_rows(rows[:1], answers + unlisted, entities, graph_schema, passages)
    assert counts["split"] == 1 and "Candidate: GONE" in out_unlisted[-1]["text"]
    retry = [r for r in out if r["meta"]["fix"] == "retry"]
    assert "D2" not in {r["meta"]["candidate_id"] for r in retry} and "D3" in {r["meta"]["candidate_id"] for r in retry}
    for r in out:
        s = r["spans"][0]
        assert r["text"][s["start"] : s["end"]] == r["meta"]["mention"]
    # A third round asks only about candidates no earlier round asked about.
    second = answers + [({**r, "answer": "reject"}, "a") for r in retry]
    third, _ = linking.fix_rows(rows[1:], second, entities, graph_schema, passages, wider=5)
    assert not {r["meta"]["candidate_id"] for r in third} & {r["meta"]["candidate_id"] for r in retry}


def test_mention_answers_override_their_group(graph_schema):
    mentions = [Mention("D", "D:0", 0, 4, "Acme", "COMPANY"), Mention("D", "D:0", 10, 14, "Acme", "COMPANY")]
    group_rows = [{"group_id": "a", "type": "COMPANY", "mentions": [["D:0", 0, 4], ["D:0", 10, 14]], "rule_ids": None}]
    answers = [
        ({"answer": "accept", "meta": {"group_id": "a", "candidate_id": "C1"}}, "x"),
        ({"answer": "accept", "meta": {"group_id": "a", "candidate_id": "C2"}}, "x"),
        ({"answer": "accept", "meta": {"group_id": "a", "mention_key": ["D:0", 10, 14], "candidate_id": "C2"}}, "x"),
        ({"answer": "reject", "meta": {"group_id": "a", "mention_key": ["D:0", 10, 14], "candidate_id": "C1"}}, "x"),
    ]
    resolved = linking.resolve(group_rows, answers)
    assert resolved["a"] == (["C1", "C2"], "answers")
    nodes = pairs.mention_nodes(mentions, group_rows, resolved, graph_schema, {}, linking.mention_answers(answers))
    assert [n.id for n in nodes[mentions[0].key]] == ["C1", "C2"]
    assert [n.id for n in nodes[mentions[1].key]] == ["C2"]


def test_gold_answers_split_mixed_groups(graph_schema):
    g = linking.MentionGroup("a", "D", "COMPANY", "Acme", [Mention("D", "D:0", 0, 4, "Acme", "COMPANY"), Mention("D", "D:0", 10, 14, "Acme", "COMPANY")])
    rows = linking.gold_answers([g], {"a": {"C1", "C2"}}, mention_ids={("D:0", 0, 4): {"C1"}, ("D:0", 10, 14): {"C2"}})
    by_mention = linking.mention_answers([(r, "gold") for r in rows])
    assert by_mention == {("D:0", 0, 4): ["C1"], ("D:0", 10, 14): ["C2"]}
    same = linking.gold_answers([g], {"a": {"C1"}}, mention_ids={("D:0", 0, 4): {"C1"}, ("D:0", 10, 14): {"C1"}})
    assert not linking.mention_answers([(r, "gold") for r in same])


def test_tokenizer_splits_and_survives_saving(tmp_path):
    import spacy

    from kg_recipes.recipes.make_tokenizer import build

    build("en", "( ) [ ] / + -").to_disk(tmp_path / "tok")
    nlp = spacy.load(tmp_path / "tok")
    assert [t.text for t in nlp("(VCM)-induced")] == ["(", "VCM", ")", "-", "induced"]


def test_llm_lines_and_failures():
    from kg_recipes.llm import LLM, proposer

    llm = LLM("key", "model", "https://example.com/v1/chat/completions")
    llm.complete = lambda prompt: "```\n1. Diabetes Mellitus\n- Diabetes\n\n* Diabetes\n```".strip("`")
    assert llm.lines("p", 5) == ["Diabetes Mellitus", "Diabetes"]

    def boom(prompt):
        llm.usage["calls"] += 1
        raise OSError("no network")

    llm.complete = boom
    propose = proposer(llm, lambda *a, n: "p")
    assert propose("x") == []
    with pytest.raises(RuntimeError):
        for _ in range(5):
            propose("x")


def test_llm_settings_need_model_and_url():
    from kg_recipes.llm import from_settings

    assert from_settings(None, "", "") is None
    with pytest.raises(ValueError, match="--llm-model and --llm-url"):
        from_settings("key", "", " ")
    llm = from_settings("key", " some-model ", "https://example.com/v1/chat/completions")
    assert (llm.model, llm.url) == ("some-model", "https://example.com/v1/chat/completions")


def test_question_text_puts_the_candidate_first_and_trims_context():
    text = "word " * 200 + "Acme makes things. " + "more " * 200
    start = text.index("Acme")
    body, spans = linking.question_text(["Candidate: Acme Corporation (COMPANY)"], text, [(start, start + 4)], context=50)
    assert body.startswith("Candidate: Acme Corporation") and "… " in body and body.endswith(" …")
    assert len(body) < 200 and [body[s["start"] : s["end"]] for s in spans] == ["Acme"]
    whole, spans = linking.question_text(["Candidate: X"], text, [(start, start + 4)], context=0)
    assert "…" not in whole and whole[spans[0]["start"] : spans[0]["end"]] == "Acme"


def test_gold_examples_include_empty_passages(graph_schema):
    passages = {"D": [{"text": "Acme sells.", "meta": {"passage_id": "D:0", "kind": "paragraph"}}, {"text": "Nothing here.", "meta": {"passage_id": "D:1", "kind": "paragraph"}}]}
    rows = [{"doc_id": "D", "mentions": [{"passage": 0, "start": 0, "end": 4, "type": "COMPANY", "ids": ["C1"]}]}]
    mentions = gold.gold_mentions(rows, passages, graph_schema)
    by_id = {p["meta"]["passage_id"]: p for p in passages["D"]}
    out = gold.spans_examples(mentions, by_id, ["D:0", "D:1"])
    assert {r["meta"]["passage_id"]: len(r["spans"]) for r in out} == {"D:0": 1, "D:1": 0}


def test_pattern_matches_keep_the_longest_unless_overlapping():
    from prodigy.models.matcher import PatternMatcher

    from kg_recipes.recipes.make_tokenizer import DEFAULT_SPLIT, build

    nlp = build("en", DEFAULT_SPLIT)
    patterns = [
        {"label": "Drug", "pattern": [{"lower": "abiraterone"}]},
        {"label": "Drug", "pattern": [{"lower": "abiraterone"}, {"lower": "acetate"}]},
    ]
    text = "Take abiraterone acetate daily."
    found = {}
    for overlapping in (False, True):
        matcher = PatternMatcher(nlp, combine_matches=True, all_examples=True, allow_overlap=overlapping)
        matcher.add_patterns(patterns)
        (_, eg), = matcher([{"text": text}])
        found[overlapping] = sorted(text[s["start"] : s["end"]] for s in eg["spans"])
    assert found[False] == ["abiraterone acetate"]
    assert found[True] == ["abiraterone", "abiraterone acetate"]


def test_query_params_cant_set_read_only():
    from kg_recipes import graph as kg_graph

    sent = {}

    class Fake(kg_graph.Neo4j):
        def __init__(self):
            pass

        def run(self, statements, *, read_only=False, timeout=300):
            sent.update(read_only=read_only, params=statements[0][1])
            return [{"columns": [], "rows": []}]

    Fake().query("RETURN 1", {"read_only": False, "statement": "x"})
    assert sent["read_only"] is True and sent["params"] == {"read_only": False, "statement": "x"}


def test_read_only_sees_through_comments_and_strings():
    import pytest

    from kg_recipes import app, graph as kg_graph

    for statement in ("LOAD/**/CSV FROM 'http://x' AS r RETURN r", "CALL /* */ dbms.listConfig()", "MATCH (n) // x\nSET n.a = 1"):
        with pytest.raises(kg_graph.Neo4jError):
            app.read_only(statement)
    assert app.read_only("MATCH (e:Entity) WHERE e.name = 'set up' RETURN e")


def test_whole_document_passage_isnt_labelled():
    doc = documents.parse_document({"doc_id": "D", "text": "One.\n\nTwo."}, whole_document=True)
    rows = list(documents.passage_rows(doc))
    assert [documents.is_whole_document(r) for r in rows] == [False, False, True]


def test_a_doc_id_is_one_document_in_one_version():
    rows = [
        {"doc_id": "D1", "version": "1", "text": "Same."},
        {"doc_id": "D2", "version": "2", "text": "Revised."},
        {"doc_id": "D3", "text": "New."},
        {"doc_id": "D3", "text": "Again."},
    ]
    parsed, problems, skipped = documents.new_documents(rows, {"D1": "1", "D2": "1"})
    assert [d.doc_id for d in parsed] == ["D3"] and skipped == 1
    assert "D2 is in an earlier batch as version 1" in problems[0] and '"version_of": "D2"' in problems[0]
    assert "D3 is also on line 3" in problems[1]
    # A new version under its own id lands on the same side of the split as the one it replaces.
    docs = [documents.parse_document({"doc_id": f"D{i}", "text": "x"}) for i in range(50)]
    newer = [documents.parse_document({"doc_id": f"D{i}-v2", "version_of": f"D{i}", "text": "y"}) for i in range(50)]
    held = {d.doc_id for d in documents.split(docs, 0.3)[1]}
    assert {d.version_of for d in documents.split(newer, 0.3)[1]} == held


def test_passages_by_id_refuses_two_versions_under_one_id():
    v1 = list(documents.passage_rows(documents.parse_document({"doc_id": "D", "version": "1", "text": "Old."})))
    v2 = list(documents.passage_rows(documents.parse_document({"doc_id": "D", "version": "2", "text": "New."})))
    assert len(documents.passages_by_id(v1 + v1)) == 1
    with pytest.raises(ValueError, match="D:0"):
        documents.passages_by_id(v1 + v2)


def test_gold_offsets_are_checked_against_their_text(graph_schema):
    doc = documents.parse_document({"doc_id": "D", "passages": [{"text": "  Acme  Corporation sells\tskates."}]}, whole_document=True)
    passages = {"D": list(documents.passage_rows(doc))}
    assert passages["D"][0]["text"] == "Acme Corporation sells skates."
    rows = [{"doc_id": "D", "mentions": [
        {"passage": 0, "start": 2, "end": 19, "text": "Acme  Corporation", "type": "COMPANY", "ids": ["C1"]},
        {"passage": 0, "start": 0, "end": 4, "text": "Acme", "type": "COMPANY"},
        {"passage": 0, "start": 0, "end": 4, "text": "Globex", "type": "COMPANY"},
        {"passage": 0, "start": 30, "end": 40, "type": "COMPANY"},
        {"passage": 1, "start": 0, "end": 4, "type": "COMPANY"},
        {"passage": 2, "start": 0, "end": 4, "type": "COMPANY"},
    ]}]
    report = gold.GoldReport()
    found = gold.gold_mentions(rows, passages, graph_schema, report)
    assert [g.mention.text for g in found] == ["Acme Corporation", "Acme"]
    assert report.realigned == 1 and report.unchecked == 1
    assert len(report.problems) == 4
    assert "'Globex' isn't in passage 0" in report.problems[0]
    assert "whole-document passage" in report.problems[2] and "no passage 2" in report.problems[3]


def test_passages_with_the_same_text_are_separate_examples():
    from kg_recipes.mentions import hashed, passage_tasks

    rows = [{"text": "Shared row.", "meta": {"passage_id": pid, "kind": "table_row"}} for pid in ("A:0", "B:0", "A:0")]
    rows.append({"text": "Shared row.", "meta": {"passage_id": "A:1", "kind": "document"}})
    tasks = list(passage_tasks(rows))
    assert [t["meta"]["passage_id"] for t in tasks] == ["A:0", "B:0"]
    assert tasks[0]["_input_hash"] != tasks[1]["_input_hash"]
    # import-gold hashes its examples the same way, whatever else they hold.
    again = hashed({**rows[0], "spans": [{"start": 0, "end": 6, "label": "X"}]})
    assert (again["_input_hash"], again["_task_hash"]) == (tasks[0]["_input_hash"], tasks[0]["_task_hash"])


def test_rows_with_the_same_text_are_told_apart():
    from kg_recipes.data import distinct_texts

    rows = [{"text": "Q", "meta": {"passage_id": p}} for p in ("A:0", "B:0", "B:0")] + [{"text": "R", "meta": {"doc_id": "C"}}]
    assert [r["text"] for r in distinct_texts(rows)] == ["Q", "Q\n\n(B:0)", "Q\n\n(B:0, 2)", "R"]

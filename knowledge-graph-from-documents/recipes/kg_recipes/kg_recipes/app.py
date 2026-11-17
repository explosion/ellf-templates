"""The service's web app: a page for people and a JSON API for programs.

The app answers straight away and starts Neo4j and loads the graph in a background
thread, so the page can show what it's doing during the first start's downloads. Every
query runs in a read-only transaction. Until the schema's checks return no rows, the
questions, views and API answer 503 with the failed checks, and the page shows them.

All URLs in the page are relative, because the cluster serves the app under
``/services/<id>/``.
"""

import json
import os
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from importlib import resources
from typing import Any, Callable, Dict, List, Optional

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from . import graph, neo4j_runtime
from .llm import LLM
from .schema import Schema

#: Set these to use a Neo4j server you already run, e.g. for a local run on a laptop.
#: The graph is loaded into it, replacing everything in its default database.
URL_ENV, USER_ENV, PASSWORD_ENV = "KG_NEO4J_URL", "KG_NEO4J_USER", "KG_NEO4J_PASSWORD"
WRITE_RE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+`?dbms|CALL\s+`?apoc)\b", re.IGNORECASE)
#: Comments and string literals, taken out before the check: a comment can hide a keyword
#: (``LOAD/**/CSV``), and a string can hold one without it being a write ('set up').
COMMENT_OR_STRING_RE = re.compile(r"/\*.*?\*/|//[^\n]*|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", re.DOTALL)


@dataclass
class Question:
    name: str
    title: str
    cypher: str
    description: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    absence: bool = False
    uses: List[str] = field(default_factory=list)


def parse_questions(text: str) -> List[Question]:
    data = json.loads(text) if text.strip() else []
    out = []
    for q in data:
        if not q.get("name") or not q.get("cypher") or not q.get("title"):
            raise ValueError(f"Every question needs a name, a title and a Cypher query: {q}")
        out.append(
            Question(
                name=q["name"],
                title=q["title"],
                cypher=q["cypher"],
                description=q.get("description", ""),
                params=dict(q.get("params") or {}),
                expected=q.get("expected"),
                absence=bool(q.get("absence", False)),
                uses=list(q.get("uses") or []),
            )
        )
    return out


def cypher_prompt(question: str, schema: Schema, examples: List[Question]) -> str:
    """The prompt that asks an LLM for one read-only Cypher query answering ``question``."""
    types = ", ".join(schema.entity_types)
    labels = ", ".join(l for g in schema.relations for l in g.labels)
    shots = "\n".join(f"Q: {q.title}\nCypher: {q.cypher}" for q in examples[:8])
    return (
        "Write one read-only Cypher query for Neo4j that answers the question.\n"
        "The graph: (:Entity {id, type, name, nil}) with type one of: " + types + ".\n"
        "Relationships between entities, named by label: " + labels + "; each has properties "
        "id, group, evidence, conditions, doc_versions, first_date, last_date, methods.\n"
        "(:Document {doc_id, version, date, title, url})-[:HAS_PASSAGE]->(:Passage {passage_id, text})"
        "-[:MENTIONS]->(:Entity). (:Passage)-[:SUPPORTS]->(:Evidence {link_id, label}).\n"
        "Return at most 100 rows. Answer with the query only, no explanation, no code fence.\n\n"
        f"{shots}\n\nQ: {question}\nCypher:"
    )


@dataclass
class State:
    status: str = "starting"
    message: str = "Starting"
    error: Optional[str] = None
    db: Optional[graph.Neo4j] = None
    summary: str = ""
    checks: List[dict] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def report(self, message: str) -> None:
        self.message = message
        print(f"[kg_graph] {message}", file=sys.stderr, flush=True)

    @property
    def checks_failed(self) -> List[dict]:
        return [c for c in self.checks if c["count"] or c["error"]]


def prepare(state: State, sources: graph.Sources) -> None:
    """Start Neo4j, build the graph and load it, then run the checks."""
    try:
        if os.environ.get(URL_ENV):
            state.report("Using the Neo4j server from the environment")
            db = graph.Neo4j(os.environ[URL_ENV], os.environ.get(USER_ENV, "neo4j"), os.environ.get(PASSWORD_ENV, ""))
        else:
            running = neo4j_runtime.start(state.report)
            db = graph.Neo4j(running.url, running.user, running.password)
        state.report("Reading the assets and datasets")
        rows = graph.assemble(sources)
        state.report("Loading the graph")
        graph.load(db, rows)
        state.summary = rows.summary()
        state.report("Running the checks")
        state.checks = graph.run_checks(db, sources.schema)
        state.db = db
        if state.checks_failed:
            state.status = "checks_failed"
            state.report(f"Loaded, but {len(state.checks_failed)} checks returned rows")
        else:
            state.status = "ready"
            state.report(f"Ready: {state.summary}")
    except Exception as e:
        state.status = "failed"
        state.error = f"{type(e).__name__}: {e}"
        state.message = "Couldn't start the graph"
        traceback.print_exc()


def typed(value: str, default: Any) -> Any:
    """A URL parameter as the type of the question's default: Cypher compares types strictly."""
    if isinstance(default, bool):
        return value.lower() in ("1", "true", "yes")
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def strings_in(rows: List[dict]) -> List[str]:
    """Every string value in the rows, lists included."""
    found = set()
    for row in rows:
        for v in row.values():
            for x in v if isinstance(v, list) else [v]:
                if isinstance(x, str) and x.strip():
                    found.add(x)
    return sorted(found)[:2000]


def with_entities(db: graph.Neo4j, result: Dict[str, Any]) -> Dict[str, Any]:
    """The result, plus the ids of the entities whose names appear in its rows, so the page
    can open them."""
    names = strings_in(result.get("rows") or [])
    found = db.query(
        "UNWIND $names AS n MATCH (e:Entity) WHERE e.name = n OR e.id = n "
        "WITH n, e ORDER BY e.id RETURN n AS name, collect(e.id)[0] AS id",
        names=names,
    ) if names else []
    return {**result, "entities": {r["name"]: r["id"] for r in found}}


# Most entities an answer's diagram shows.
SUBGRAPH_LIMIT = 150


def read_only(statement: str) -> str:
    if WRITE_RE.search(COMMENT_OR_STRING_RE.sub(" ", statement)):
        raise graph.Neo4jError("Only read-only queries are allowed.")
    return statement


def create_app(
    sources: graph.Sources,
    questions: List[Question],
    names: Dict[str, str],
    scores: Optional[dict] = None,
    llm: Optional[LLM] = None,
    background: bool = True,
) -> Starlette:
    state = State()
    by_name = {q.name: q for q in questions}
    directed = {g.name: g.directed for g in sources.schema.relations}
    if background:
        threading.Thread(target=prepare, args=(state, sources), daemon=True).start()
    else:
        prepare(state, sources)

    def needs_db(handler: Callable[[Request, graph.Neo4j], Any]) -> Callable[[Request], JSONResponse]:
        def endpoint(request: Request) -> JSONResponse:
            if state.db is None:
                return JSONResponse({"error": state.error or state.message}, status_code=503)
            if state.checks_failed:
                return JSONResponse({"error": "The graph failed its checks.", "checks": state.checks_failed}, status_code=503)
            try:
                return JSONResponse(handler(request, state.db))
            except KeyError as e:
                return JSONResponse({"error": f"Not found: {e.args[0]}"}, status_code=404)
            except (graph.Neo4jError, ValueError) as e:
                return JSONResponse({"error": str(e)}, status_code=400)

        return endpoint

    async def threaded(request: Request, handler) -> JSONResponse:
        # Queries run in a worker thread, so a slow one doesn't hold up other requests.
        return await run_in_threadpool(needs_db(handler), request)

    def index(request: Request) -> HTMLResponse:
        return HTMLResponse(resources.files(__package__).joinpath("static/index.html").read_text(encoding="utf-8"))

    def status(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": state.status,
                "message": state.message,
                "error": state.error,
                "summary": state.summary,
                "checks": state.checks,
                "sources": names,
                "plain_language": llm is not None,
                "seconds": round(time.monotonic() - state.started),
            }
        )

    def question_list(request: Request) -> JSONResponse:
        return JSONResponse(
            [
                {"name": q.name, "title": q.title, "description": q.description, "params": q.params, "absence": q.absence, "uses": q.uses}
                for q in questions
            ]
        )

    def figures_for(q: Question) -> dict:
        if not scores:
            return {}
        links = scores.get("graph", {}).get("links", {})
        return {label: links[label] for label in q.uses if label in links}

    def question(request: Request, db: graph.Neo4j) -> Dict[str, Any]:
        q = by_name.get(request.path_params["name"])
        if q is None:
            raise KeyError(request.path_params["name"])
        params = {k: typed(request.query_params[k], v) if k in request.query_params else v for k, v in q.params.items()}
        rows = db.query(q.cypher, params)
        result = {"name": q.name, "title": q.title, "cypher": q.cypher, "params": params, "rows": rows, "checked": True, "figures": figures_for(q), "absence": q.absence}
        return with_entities(db, result)

    def node(request: Request, db: graph.Neo4j) -> Dict[str, Any]:
        found = db.query("MATCH (e:Entity {id: $id}) RETURN e", id=request.path_params["id"])
        if not found:
            raise KeyError(request.path_params["id"])
        links = db.query(
            "MATCH (e:Entity {id: $id})-[r]-(o:Entity) "
            "RETURN type(r) AS label, startNode(r).id = $id AS outgoing, r.id AS link_id, r.evidence AS evidence, "
            "r.conditions AS conditions, r.group AS group, o.id AS other_id, o.name AS other_name, o.type AS other_type "
            "ORDER BY r.evidence DESC LIMIT 200",
            id=request.path_params["id"],
        )
        for l in links:
            l["directed"] = directed.get(l["group"], True)
        docs = db.query(
            "MATCH (d:Document)-[:HAS_PASSAGE]->(:Passage)-[:MENTIONS]->(:Entity {id: $id}) "
            "RETURN d.doc_id AS doc_id, d.title AS title, count(*) AS mentions ORDER BY mentions DESC LIMIT 50",
            id=request.path_params["id"],
        )
        return {"entity": found[0]["e"], "links": links, "documents": docs}

    def link(request: Request, db: graph.Neo4j) -> Dict[str, Any]:
        lid = request.path_params["id"]
        found = db.query(
            "MATCH (h:Entity)-[r {id: $id}]->(t:Entity) RETURN type(r) AS label, properties(r) AS props, "
            "h.id AS head_id, h.name AS head_name, t.id AS tail_id, t.name AS tail_name",
            id=lid,
        )
        if not found:
            raise KeyError(lid)
        ends = [found[0]["head_id"], found[0]["tail_id"]]
        # Where the two entities are mentioned in each passage, so the page can mark them.
        evidence = db.query(
            "MATCH (p:Passage)-[:SUPPORTS]->(v:Evidence {link_id: $id}) "
            "OPTIONAL MATCH (p)-[m:MENTIONS]->(e:Entity) WHERE e.id IN $ends "
            "WITH v, p, collect(CASE WHEN m IS NULL THEN null ELSE {start: m.start, end: m.end, entity: e.id} END) AS marks "
            "RETURN v.doc_id AS doc_id, v.doc_version AS doc_version, v.doc_date AS doc_date, v.conditions AS conditions, "
            "v.settled_by AS settled_by, v.answers AS answers, p.passage_id AS passage_id, p.text AS text, p.section AS section, marks",
            id=lid,
            ends=ends,
        )
        for e in evidence:
            e["answers"] = json.loads(e["answers"] or "{}")
        return {**found[0], "evidence": evidence}

    def search(request: Request, db: graph.Neo4j) -> List[Dict[str, Any]]:
        q = request.query_params.get("q", "").strip().lower()
        if not q:
            return db.query("MATCH (e:Entity)-[r]-(:Entity) RETURN e.id AS id, e.name AS name, e.type AS type, count(r) AS links ORDER BY links DESC LIMIT 30")
        return db.query(
            "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS $q OR toLower(e.id) = $q "
            "OPTIONAL MATCH (e)-[r]-(:Entity) RETURN e.id AS id, e.name AS name, e.type AS type, count(r) AS links "
            "ORDER BY links DESC LIMIT 30",
            q=q,
        )

    def checks(request: Request) -> JSONResponse:
        return JSONResponse({"status": state.status, "checks": state.checks})

    def score_figures(request: Request) -> JSONResponse:
        return JSONResponse(scores or {})

    async def subgraph(request: Request) -> JSONResponse:
        body = await request.json()
        ids = [str(i) for i in body.get("ids") or []][:SUBGRAPH_LIMIT]

        def among(req: Request, db: graph.Neo4j) -> Dict[str, Any]:
            nodes = db.query("MATCH (e:Entity) WHERE e.id IN $ids RETURN e.id AS id, e.name AS name, e.type AS type", ids=ids)
            links = db.query(
                "MATCH (a:Entity)-[r]->(b:Entity) WHERE a.id IN $ids AND b.id IN $ids AND r.group IS NOT NULL "
                "RETURN r.id AS link_id, a.id AS head, b.id AS tail, type(r) AS label, r.group AS group, r.evidence AS evidence",
                ids=ids,
            )
            for l in links:
                l["directed"] = directed.get(l["group"], True)
            return {"nodes": nodes, "links": links}

        return await threaded(request, among)

    async def cypher(request: Request) -> JSONResponse:
        body = await request.json()
        statement = str(body.get("query", "")).strip()
        if not statement:
            return JSONResponse({"error": "Type a query first."}, status_code=400)
        params = body.get("params") or {}
        if not isinstance(params, dict):
            return JSONResponse({"error": "params must be an object."}, status_code=400)
        return await threaded(request, lambda req, db: with_entities(db, {"rows": db.query(read_only(statement), params), "checked": False}))

    async def ask(request: Request) -> JSONResponse:
        if llm is None:
            return JSONResponse({"error": "Plain-language questions aren't set up for this service."}, status_code=404)
        body = await request.json()
        text = str(body.get("question", "")).strip()
        if not text:
            return JSONResponse({"error": "Type a question first."}, status_code=400)
        try:
            statement = await run_in_threadpool(llm.complete, cypher_prompt(text, sources.schema, questions))
            statement = statement.removeprefix("cypher").strip()
        except Exception as e:
            return JSONResponse({"error": f"The LLM couldn't write a query: {e}"}, status_code=502)
        response = await threaded(
            request, lambda req, db: with_entities(db, {"question": text, "cypher": statement, "rows": db.query(read_only(statement)), "checked": False})
        )
        if response.status_code == 400:
            data = json.loads(response.body)
            return JSONResponse({**data, "cypher": statement, "checked": False}, status_code=400)
        return response

    def export(request: Request):
        if state.db is None or state.checks_failed:
            return JSONResponse({"error": state.error or "The graph isn't ready."}, status_code=503)
        db = state.db

        def rows():
            for e in db.query("MATCH (e:Entity) RETURN e"):
                yield json.dumps({"kind": "entity", **e["e"]}) + "\n"
            for r in db.query(
                "MATCH (h:Entity)-[r]->(t:Entity) RETURN type(r) AS label, h.id AS head, t.id AS tail, properties(r) AS props"
            ):
                yield json.dumps({"kind": "link", "label": r["label"], "head": r["head"], "tail": r["tail"], **r["props"]}) + "\n"
            for v in db.query("MATCH (p:Passage)-[:SUPPORTS]->(v:Evidence) RETURN v, p.passage_id AS passage_id"):
                yield json.dumps({"kind": "evidence", "passage_id": v["passage_id"], **v["v"]}) + "\n"

        return StreamingResponse(rows(), media_type="application/x-ndjson")

    def wrap(handler):
        async def endpoint(request: Request) -> JSONResponse:
            return await threaded(request, handler)

        return endpoint

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", status),
            Route("/api/checks", checks),
            Route("/api/scores", score_figures),
            Route("/api/questions", question_list),
            Route("/api/questions/{name}", wrap(question)),
            Route("/api/node/{id:path}", wrap(node)),
            Route("/api/link/{id}", wrap(link)),
            Route("/api/search", wrap(search)),
            Route("/api/subgraph", subgraph, methods=["POST"]),
            Route("/api/cypher", cypher, methods=["POST"]),
            Route("/api/ask", ask, methods=["POST"]),
            Route("/api/export", export),
        ]
    )

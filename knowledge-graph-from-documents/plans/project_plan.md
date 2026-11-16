# Knowledge Graph from Documents

## Goal

A set of documents mentions entities and the relations between them, and the
questions that matter can only be answered across many documents at once. This
project builds a graph of those entities and relations, where every link opens the
passages behind it, and measures how far the graph can be trusted: each step on its
own, the finished graph, and the answers to the questions it was built for.

Nothing in the method depends on the documents: where they come from, which entity
types they mention and which relation types matter are all settings of this project.

## Your project

<!-- Fill in before anything is built. -->

| | |
|---|---|
| Documents | |
| How many, and how often new ones arrive | |
| Who uses the graph, and for what decision | |
| Who reads it, and does anything read it through the API? | |
| What a wrong link costs, and what a missing one costs | |
| May the text be sent to an LLM or other model provider? | |
| Existing gold labels, if any | |

## Questions

The questions decide what the graph holds; anything no question uses is left out.
For each one, write the answer you expect on a few documents you know well. Those
answers are the first test of the finished graph.

| Question | Nodes and links it needs | Expected answer on the test documents | Is it about absence? |
|---|---|---|---|
| | | | |

A question about absence, one that asks which entities have no link of some type, is
only as good as the recall of the link whose absence it counts. Mark those: the
evaluation measures that recall for each one.

The questions are kept in `config/questions.json`: a title, how to read the answer,
a Cypher query with its parameters, and the expected answer. The service and
`scripts/score.py` use the same file.

## Schema

`config/graph_schema.json` is the one place that says what the graph holds. It's
published as @@Assets/Graph schema@@, and every job and the service read it from
there; a change is a new version of that asset, and the jobs that read it are
created again.

- **Entity types:** for each, which list its mentions are linked to
  (@@Assets/Entity list@@) and at which level of that list; whether a mention may
  link to more than one entry; and what happens to a mention with no entry (NIL):
  dropped, or kept as a node of its own.
- **Relation types:** the entity types at each end, the labels, NONE, whether one
  passage can state more than one label for the same pair, the
  conditions a link carries when a relation only holds under some of them, and the
  rule that turns passages into one link (any passage, the most recent document, a
  majority).
- **What every link carries:** the document, its version and date, the passage, the
  version of the entity list, and the method behind each label: the rule, or the
  labeller with its model and version, and the version of the label scheme and
  guidelines.
- **Checks:** Cypher queries that must return no rows, run on every build. A row is
  a contradiction or an impossible fact.

## Choosing a method

Every component needs its own method: mentions for each entity type, linking for
each list, and each relation type. Nothing in this template fixes one. Choose them
with `/ellf-project`, from the documents, the questions and the constraints in Your
project; it records each choice and why in the Decision Log. Set up the annotation
for each with `/ellf-annotate`, and training, if a model is chosen, with
`/ellf-train`.

What's specific to a graph:

- **The cost of a link decides the bar.** A wrong link creates an answer and a
  missing one hides it. For each component, write down which questions use it and
  which mistake costs more there.
- **Questions about absence need recall.** A component behind one is chosen for
  recall first.
- **Linking can't beat its candidates.** Measure candidate recall before choosing
  how to pick between candidates. When it's low, the evaluation shows why: the
  mentions whose right entry no source found, and which source found the rest. That
  decides whether to add broader entries, names an LLM proposes, a better entity list,
  or nothing, since each source also adds questions.
- **Compare on the same gold.** Run every shortlisted option, or combination of
  options, as a labeller on the component's task, score them all on the same gold
  labels, and keep the cheapest that meets the bar.

## Approach

### 1. Documents in one format

@@Actions/add-documents@@ turns the source into the documents asset (`documents`): one row per
passage (a paragraph or a table row, with its section), each with its document's id,
version and date. A passage may also be a whole document, when that's where the
relations are stated. Sources in other formats (PDF, XML, a shared task's files) get a
small converter in the project that writes the documents format; nothing in the
recipes knows where documents come from.

Before anything is labelled, it sets whole documents aside as
the evaluation documents asset (`documents-eval`): chosen at random, by document, never split across
labelling and evaluation. All their passages are kept, including those no rule
flags, so the evaluation can see what the rules miss.

### 2. Mentions

@@Actions/make-tokenizer@@ saves the tokenizer asset (`tokenizer`), which splits words where the
documents need it, e.g. at brackets and hyphens inside names: a mention can only start
and end where the tokenizer splits, and every step that reads mentions uses the same
one. @@Tasks/mentions@@ marks the mentions of each entity type in the passages.
@@Actions/find-mentions@@ saves the mentions found by rules or a pretrained model to
the task's dataset, each method under its own annotator name, so they're scored like
any other labeller. Labelled with the method chosen for each entity type (see
Choosing a method), and settled in @@Tasks/mentions-review@@.

### 3. Entity linking

Each mention is linked to entries in @@Assets/Entity list@@, or to NIL. The list
holds an id, a name, other names, a type and a short description for each entry, at
the level the schema chooses for that entity type.

- **Candidates:** @@Actions/link-candidates@@ normalises each mention, expands
  abbreviations defined in the same document, and looks it up by name, other names
  and approximate match, keeping only entries of the mention's type, up to a set
  number per mention. For mentions no name matches exactly, two sources are optional:
  the broader entries of the candidates found, when the list has a hierarchy, and
  names an LLM proposes for the mention, looked up the same way. Which ones this
  project uses is decided from the evaluation (see Choosing a method).
- **Linked by rule:** a mention whose only candidate matches a name exactly. This
  rule is also the baseline.
- **Linked by a question:** the rest go to @@Tasks/links@@, one yes/no question per
  mention and candidate, with the passage and the entry's description. Each name is
  asked once per document, and the answer carries to its other mentions there. NIL is
  no to every candidate, and a mention can be yes to more than one candidate.
  Answered with the method chosen for linking (see Choosing a method), and settled in
  @@Tasks/links-review@@.
- **A second round:** @@Actions/fix-links@@ asks again where the settled answers leave
  a name unresolved. When every candidate was rejected, it offers a wider search;
  when a name was linked to two entries of a type that links a mention to one (the
  same name meaning two things in one document), it asks about each mention. The
  same task and review settle them, in @@Tasks/links-fix@@ and
  @@Tasks/links-fix-review@@; an answer about one mention overrides its name's.
- **NIL:** the schema says, per entity type, whether a NIL mention is dropped or
  becomes its own node; NIL nodes are grouped by name across documents.

Mentions linked to the same entry become one node. Expressions such as "the
company" aren't linked unless the schema adds a coreference step.

### 4. Relations

`make-pairs`, once per relation group, writes one row per candidate pair the schema allows in a
passage, with the head marked `[[like this]]` and the tail `{{like this}}` (both
`[[ ]]` when the relation has no direction), and the conditions found by rule.
The relations task of each group asks one question per row: which relation the passage states
between the two marked entities, or NONE. Labelled with the method chosen for each
relation type (see Choosing a method), and settled in that group's review.

There's no built-in relation model, and LLM agents can't use the relations
interface, so pairs are text classification, which models, agents and people can
all label.

### 5. The graph and its interface

@@Services/knowledge-graph@@ runs Neo4j inside the service, so the graph lives on
your cluster and nowhere else. It's created with the schema, the questions file, the
document assets and the settled datasets. On every start it rebuilds the graph from
them and runs the checks; it doesn't start serving if a check returns rows. A
service's arguments are fixed when it's created, so new documents or datasets mean
creating it again.

**For people**, a page open to project members, with three tabs:

- **Questions:** each question with a button that runs it, its answer, and the
  figures behind it: the precision of the link types it uses and, for questions
  about absence, the recall it depends on. Entity names in an answer open the entity,
  and the answer can be drawn as a diagram of its entities and the links between them.
- **Entities:** search by name or id; an entity's links, drawn as a diagram of its
  neighbours and listed in a table, and for every link the
  passages behind it with both entities marked, each labeller's answer, the method
  and the document version.
- **Query and API:** read-only Cypher with example queries, and the API routes.

New questions in plain language are asked at the top of the Questions tab: an LLM turns
each into a read-only Cypher query, shown with the answer and marked as unchecked, since
only the questions file is tested against expected answers (`score.py questions`).

The results of the checks are shown above the tabs.

**For programs**, an HTTP API under the service's URL, with the token from
`ellf services url`:

- run a named question with parameters;
- run read-only Cypher;
- read a node with its neighbours, or a link with its evidence;
- export the graph, nodes and links with their provenance, as JSON lines.

The same calls can be offered to MCP clients. Every request is read-only: Neo4j
listens only inside the service, and writes are refused.

## Evaluation

The same three levels for every project. A dataset that comes with gold labels
loads them with @@Actions/import-gold@@; otherwise the evaluation tasks below make
them, from the evaluation documents asset (`documents-eval`) only.

### Each component

| Component | Gold labels | What's reported |
|---|---|---|
| Mentions | a person marks every mention in the evaluation documents, in @@Tasks/mentions-eval@@, settled into @@Datasets/mentions-gold@@ | precision and recall per entity type, for each method compared |
| Entity linking | a person links every gold mention, NIL included, in @@Tasks/links-eval@@, into @@Datasets/links-gold@@ | candidate recall (the ceiling), accuracy when the right entry is a candidate, NIL precision and recall, per entity type and per document, and every error sorted as: right entry not a candidate, wrong entry, wrongly NIL, wrong type |
| Relations | a person labels each group's evaluation pairs, blind, alongside each method compared, settled into that group's gold dataset | accuracy per label, wrong and missed links, for the rules and each method compared |

`scripts/score.py` reports every figure with a 95% interval. Roughly 100 examples
tell 80% from 90%; telling 90% from 91% needs about 1,000. A method that answers
with a confidence is run on the evaluation set with no threshold; its threshold is
chosen from how accuracy and the share of rows it answers change as the threshold
rises, and the model version, the threshold and that curve are recorded.

### The whole graph

- **Precision of links:** @@Actions/sample-links@@ draws a random sample of the
  graph's links per link type, grouped by document; a person checks each against
  its passages in @@Tasks/link-check@@. Reported per link type with a 95% interval.
  This is the figure to quote: a link combines passages, so passage accuracy isn't
  link accuracy.
- **Recall:** the graph itself covers documents with no gold labels, so recall is
  measured on the evaluation documents: a graph built there from the labellers'
  answers, compared with the gold graph (`scripts/build_graph.py`, then
  `score.py compare`). Every answer to an absence question states the recall of the
  link it counts.
- **Where the errors come from:** start from the gold graph and replace the gold with the
  labellers' answers one step at a time, from the last: relations first, which costs
  nothing more since the evaluation pairs are already answered; then linking, which
  means building and labelling the pairs the labellers' links give; then mentions. Each
  step reads the one before it, so a step can only be measured with everything after it
  answered again. The step that loses most is the one to improve.
- **The questions:** run each question on the evaluation documents and compare with
  the expected answers written at the start.

### Real world

Compare the graph with a record made independently of it: a curated database, an
official table, or what later documents report. Say what the record covers, and
count matching errors separately from extraction errors.

## Results

### Components

| Component | Method | Precision | Recall | Accuracy | 95% interval |
|---|---|---|---|---|---|
| | | | | | |

### The graph

| Link type | Links checked | Precision (95% interval) | Recall | Weakest component |
|---|---|---|---|---|
| | | | | |

### Questions

| Question | Expected | Graph's answer | Recall it depends on |
|---|---|---|---|
| | | | |

## Roadmap

### Set up
- [ ] Fill in Your project and the questions, with expected answers
- [ ] Write the schema in `config/graph_schema.json` and the questions in `config/questions.json`, and publish both
- [ ] Choose where words split for this text, and save the tokenizer asset with @@Actions/make-tokenizer@@
- [ ] Add the documents with @@Actions/add-documents@@, setting the evaluation documents aside
- [ ] Load gold labels with @@Actions/import-gold@@, if the documents have them

### Each component, in pipeline order
- [ ] Check each task's interface with `/ellf-annotate` on the longest documents before creating the rest
- [ ] Mentions: shortlist methods, pilot in @@Tasks/mentions@@, score each on the gold labels, choose
- [ ] Entity linking: candidates and their recall, with and without the optional sources; pilot in @@Tasks/links@@, score with NIL, choose
- [ ] Entity linking: a second round with @@Actions/fix-links@@ where the answers leave names unresolved
- [ ] Relations: pairs, pilot in each relation group's task, score the rules and each method, choose
- [ ] Gold labels for the evaluation documents, for each component
- [ ] Label everything with the chosen methods, and settle the conflicts

### The graph
- [ ] Start @@Services/knowledge-graph@@; the checks return no rows
- [ ] The page: questions with their figures, node views, evidence
- [ ] The API, with a token from `ellf services url`
- [ ] Optional: questions in plain language
- [ ] Check a sample of links in @@Tasks/link-check@@ and report precision per link type
- [ ] Recall on the evaluation documents, from the relation step back as far as the questions need
- [ ] Compare the questions' answers with the expected ones
- [ ] Real-world check against an independent record

## Decisions needed

1. **The questions**, and what a wrong or missing answer costs: they set how
   accurate each link type must be.
2. **The method for each component**, from the shortlist and its scores, and its
   confidence threshold where it has one.
3. **For each entity type**, the level of its list and what happens to NIL mentions.
4. **Whether the graph is good enough** for its use, from the link precision and the
   recall behind each absence question.

## Limitations

- Recall can only be estimated, from the evaluation documents; what they don't
  contain isn't measured.
- Linking is limited by the list: an entity it doesn't hold is NIL, however it's
  written, and the list's level and version decide what counts as one entity.
- The graph holds what the documents state, as of their versions; a fact a later
  version changed is answered for the version it came from.
- Answers to plain-language questions can be wrong in ways the reader can't see.

## Progress Log
<!-- Most recent first. -->

## Decision Log

- **Questions first, each with an expected answer**: _Rationale: a graph built before its questions holds everything and answers nothing, and an expected answer is the only test of a question that needs no labels._
- **One schema file for every job and the service**: _Rationale: other documents change the settings, not the code._
- **Methods are chosen per component, per project, from scores on the same gold labels**: _Rationale: the right method depends on the data, the questions and the constraints, and only a measured comparison shows it._
- **Rules and pretrained models are labellers too**: their answers are saved under their own annotator names. _Rationale: the simplest reliable method can only be chosen if it's scored like the others._
- **Finding mentions and linking them are separate steps**: _Rationale: they fail in different ways, and a linker can never be better than the share of mentions whose right entry is among its candidates._
- **Linking as yes/no questions, one per mention and candidate**: _Rationale: a yes/no answer is quick for people and possible for any model, and NIL and several entries need no special case._
- **One question per name per document, and a second round per mention only where answers disagree**: _Rationale: most names mean one thing within a document, so asking once saves questions; the few that don't show up as two accepted entries, and only those are asked mention by mention._
- **Optional candidate sources, chosen from the evaluation**: _Rationale: each adds questions and, for an LLM, cost and data sent out; only the evaluation shows whether they find right entries the names miss._
- **Relations as one question per marked pair**: _Rationale: models, agents and people can all answer it, and both ends are fixed before anyone reads._
- **Evaluation documents set aside by document, before labelling, unfiltered**: _Rationale: passages from one document in both sets inflate scores, and a sample of passages the rules found can't measure what they miss._
- **Precision of links from a checked sample, reported with an interval**: _Rationale: a link combines passages, so passage accuracy isn't link accuracy, and a figure without an interval can't be compared._
- **Absence answers state their recall**: _Rationale: a link the pipeline missed looks the same as a link that doesn't exist._
- **Every link carries its document version and method**: _Rationale: documents are revised and methods change, and an answer that can't be traced to both can't be checked._
- **Plain-language answers are marked unchecked**: _Rationale: a generated query can be wrong in ways the reader can't see, so only questions tested against expected answers are presented as checked._
- **Built-in recipes for labelling; the template's own package only for the graph's steps**: _Rationale: the template has to work on any cluster, so its labellers are built-in task and agent recipes, and its package holds only what no built-in recipe does (documents, tokenizer, candidates, pairs, the service). Custom labelling packages a cluster happens to have are options for `/ellf-project` to raise, not steps of the method._
- **Datasets chosen per component, at import**: _Rationale: how many a component needs follows from its labellers and the gold labels (one labeller needs no review, a Gold labels asset needs no evaluation reviews), so a fixed set either has empty datasets and reviews nobody runs, or misses the ones a project needs._

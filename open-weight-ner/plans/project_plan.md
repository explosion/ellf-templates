# NER Data from a Panel of Open-Weight LLMs

## Goal

Named-entity annotations for our texts, good enough to train and evaluate a model
on, without paying an LLM provider per token or annotating every text by hand. A
panel of open-weight models on our own GPU annotates every text; a consensus model
combines their answers and learns how far to trust each one; people spend a short
review on the entities the consensus is least sure of. The outcome is a
silver-standard dataset, @@Datasets/ner_consensus_reviewed@@, with a confidence for
every entity, and a report of how accurate each model was.

One strong commercial LLM is the usual alternative. A panel of smaller models makes
more mistakes each, but different ones, and a consensus that knows which model to
believe where, anchored by a few hundred human answers, can do better than any one of
them.

## Data and labels

<!-- Fill in: what the texts are, how many, and what the labels are for. -->

| | |
|---|---|
| Texts | @@Assets/Texts@@ |
| Labels and definitions | @@Assets/NER labels@@ |
| Guidelines | @@Assets/NER guidelines@@ |
| What the data is for | |

The guidelines matter more than usual: the models and the reviewers both read them,
and most disagreements between models are about conventions (where a name starts and
ends, which label a name gets when it could be two), not facts. Settle those in the
guidelines before running the panel.

## Approach

1. **Serve the panel.** @@Actions/Download Ollama models@@ puts Ollama and the three
   models on shared storage as @@Assets/ollama-models@@, and @@Services/Open-weight LLMs@@
   serves them on a GPU behind an OpenAI-compatible API. It stops itself when idle.
2. **Annotate.** Each model annotates every text in its own batch action, one after
   another: @@Actions/Annotate: gpt-oss 20B@@, @@Actions/Annotate: Gemma 4 26B-A4B@@ and
   @@Actions/Annotate: Mistral Small 3.2 24B@@. A run that stops resumes where it was.
   The merge actions, @@Actions/Merge: gpt-oss 20B@@, @@Actions/Merge: Gemma 4 26B-A4B@@
   and @@Actions/Merge: Mistral Small 3.2 24B@@, save each model's answers to
   @@Datasets/ner_panel@@ under its name.
3. **Correct systematic errors.** Look at where each model disagrees with the
   consensus (after a first consensus run) and write the errors the guidelines rule
   out as rules in @@Assets/Correction rules@@. @@Actions/Apply correction rules@@
   applies them to every model alike, into @@Datasets/ner_panel_rules@@, with
   @@Assets/en_core_web_sm@@ from @@Actions/Download spaCy pipeline@@ for the rules that
   parse the text. Boundary conventions are the most valuable to fix: models that
   disagree on a boundary split their votes, and the entity can be lost.
4. **Consensus.** @@Actions/Consensus: panel@@ fits the consensus model into
   @@Datasets/ner_consensus_panel@@, with every candidate entity and its posterior.
   Its annotators report says how accurate each model is per label; a model that
   lowers the consensus can be left out of later runs.
5. **Review.** One person answers yes or no about the uncertain entities in
   @@Tasks/Review uncertain entities@@, into @@Datasets/ner_reviews@@: typically up to
   about one question per text, a few seconds each.
6. **Consensus with the reviews.** @@Actions/Consensus: reviewed@@ refits the model
   with the answers as certain, into @@Datasets/ner_consensus_reviewed@@. The answers
   fix the entities reviewed and anchor what the model learns about each annotator,
   which corrects the rest too.
7. **Evaluate (optional).** Correct a random sample text by text in
   @@Tasks/Correct the consensus@@, into @@Datasets/ner_corrections@@, and use it to
   measure the consensus, and later a model trained on it.

## Decisions

<!-- Record the choices made along the way, with why: labels and conventions settled,
     models added or left out, rules added, review thresholds. -->

## Next steps

- Train a model on @@Datasets/ner_consensus_reviewed@@, evaluated on
  @@Datasets/ner_corrections@@.
- Annotate more texts with the same panel, rules and guidelines: the consensus and the
  review scale with them, and a larger review keeps improving the consensus.

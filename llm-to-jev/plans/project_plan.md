# Replacing an LLM Classifier with Jev

## Goal

A classification decision in our product is made by prompting a general-purpose LLM
and parsing its text output. This project tests whether Jev, a model from TypeSafe
that answers typed questions with probabilities instead of generating text, can
replace the LLM. It settles the label definitions Jev needs, and ends with a
confidence cut-off: records Jev is confident about are decided by Jev, and the rest
go to a person in @@Tasks/review@@.

Prompting an LLM and parsing its reply has three operational costs: each call is
relatively expensive, replies sometimes fail to parse, and the classifier is exposed
to the provider's slowdowns. The LLM also gives no usable score, so a decision can't
be made more or less conservative without rewriting the prompt. Jev's answers are
typed, so there is nothing to parse, and each comes with a probability that can be
thresholded. The question is whether its decisions are as good.

## Current system

<!-- Fill in: what the classifier decides and where its output is used. -->

| | |
|---|---|
| Decision | |
| Labels | @@Assets/classifier-labels@@ |
| Current model and prompt | |
| Volume | |
| Where the output goes | |
| Sample for comparison | @@Assets/llm-labelled-sample@@ |

## Approach

We deliberately don't build a human gold standard first. Gold sets for tasks like
this mostly show that the category definitions are vague. Instead, the current LLM
is the reference, and human effort goes only where the two systems disagree. Where
both answers are defensible, we choose a definition and write it down, rather than
counting either system as wrong.

1. **Baseline.** @@Actions/jev-baseline@@ runs Jev over a sample of past records
   that carry the LLM's label, with the same label definitions and a one- or
   two-sentence description of the setting. It saves every answer to
   @@Datasets/jev_baseline@@. We measure agreement and Cohen's κ.
2. **Judge the disagreements.** One annotator labels a small blind sample in
   @@Tasks/adjudicate@@: a few records of each kind of disagreement, plus some
   records where both agree but Jev is unsure. They choose among the labels in
   @@Assets/adjudication-labels@@, which add UNCLEAR ("I could defend more than one
   answer"), following @@Assets/adjudication-guidelines@@. They aren't shown either
   system's answer. Their labels go to @@Datasets/adjudication@@.
3. **Write rules.** Where the judging shows a consistent pattern, we add it as a
   sentence to Jev's instructions. @@Actions/jev-rules@@ reruns the sample into
   @@Datasets/jev_rules@@, and we count again. Repeat with a new rules action if
   needed.
4. **Choose a cut-off.** We read the disagreements just above each candidate
   confidence value and pick the lowest one where Jev's answers are defensible.
5. **Hand over.** @@Actions/jev-confident@@ saves the answers at or above the cut-off
   to @@Datasets/jev_confident@@, and @@Tasks/review@@ shows people only the rest,
   with @@Assets/review-guidelines@@. Their labels go to @@Datasets/review@@.

The judged sample is small (tens of records), so we report raw counts, not accuracy
estimates. Rule results are measured on the records the rules were written from, so
they show that a rule works as intended, not how accurate it is on new data.

## Jev

Jev answers a **state** (the text to classify) and typed **questions**, each with
free-text **instructions** and **criteria** (a short definition per answer). With
one label, it's a **yes/no** question and Jev returns the probability that the label
applies. With several exclusive labels, it's a **choice**: Jev returns the chosen
label, a probability for each, and its confidence in the choice.

The `textcat_jev` action sends each text as the state and builds the question from
the label scheme and the instructions. A record's **confidence** is the probability
Jev gives the answer it chose: for yes/no that is p or 1 − p, whichever is larger, so
it's always at least 0.5; for a choice it can be lower. The comparison runs use
`--min-confidence 0.0` so every answer is saved.

## Measuring

`scripts/jev_eval.py` scores exported datasets:

- `agreement` on a run: agreement, κ, agreement by confidence band, and records
  sent to a person at each cut-off. κ corrects agreement for chance, which matters
  when one label dominates.
- `sample` on the baseline run builds the blind adjudication input.
- `adjudicated` on the adjudication against the baseline and rules runs: how many
  judged records each system matches, and whose answer the annotator chose on the
  disagreements.

| Measure | Baseline | With rules |
|---|---|---|
| Records | | |
| Agreement, κ | | |
| Annotator chose Jev / LLM on disagreements | | — |
| Judged matches: LLM / Jev | | |
| Records below the cut-off | | |

## Rules

<!-- One bullet per rule added to config/instructions_rules.txt, with the pattern
from the adjudication that motivated it. -->

## Decisions needed

1. **Sign off the rules**: each is a business choice about a definition.
2. **The cut-off**, and what happens below it: the review task, falling back to the
   current LLM, or a default action.
3. **Sending data to TypeSafe**: confirm the texts may be sent to its API.
4. **Shadow run**: run Jev alongside the LLM in production for a week, logging both
   decisions and Jev's cost and latency, and switch over when the live comparison
   matches the offline one.

## Limitations

- The judged sample is small and comes from one annotator.
- Rule results are measured on the records the rules were written from.
- Cost and latency per call aren't measured until the shadow run.

## Progress Log
<!-- Most recent first. Shared by Assistant and Coding Agent. -->

## Decision Log

- **The existing LLM is the reference**: measure agreement first, and use humans
  only on disagreements. _Rationale: the question is whether Jev is a drop-in, and
  gold sets mainly show that the category definitions are vague._
- **Annotation is economical and results-led**: tens of adjudications, and training
  data only if a systematic Jev failure shows up. _Rationale: Jev only has to match
  the LLM, and choosing a cut-off needs far fewer labels than training._
- **Definitions may follow Jev's natural boundary**: "both defensible" disagreements
  are settled by a business choice, not re-annotation. _Rationale: the requirements
  are usually underspecified, and a consistent, calibrated boundary is worth more
  than an arbitrary one._
- **Business rules go in the instructions**: one sentence per rule. _Rationale: a
  rule moves only the records it covers, at high confidence, without training
  data._

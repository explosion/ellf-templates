# Replacing an LLM Classifier with Jev

## Goal

A classification decision in our product is made by prompting a generative LLM and
parsing its reply. This project evaluates moving it to Jev, a model from TypeSafe that
answers typed questions with calibrated probabilities instead of text, and carries
the move out. The outcome is an optimised Jev configuration (instructions, label
definitions and thresholds) that our system runs on its own in production.

Jev is generally much cheaper to run than a generative model, there is no reply to
parse, and its probabilities let a decision be made more or less conservative
without rewriting the prompt. But it isn't always a drop-in replacement: it works
differently, so the prompt may need adjusting, and accuracy may be higher or lower.
This project finds out which, with about an hour of annotation.

## Current system

<!-- Fill in: what the classifier decides and where its output is used. -->

| | |
|---|---|
| Decision | |
| Labels | @@Assets/classifier-labels@@ |
| Current model and prompt | |
| Volume and cost | |
| Where the output goes | |
| Sample for comparison | @@Assets/llm-labelled-sample@@ |

## Approach

The current LLM is the reference: we measure how often Jev agrees with it, and spend
human effort only where that leaves questions. Where both answers are defensible, we
choose a definition and write it down, rather than counting either system as wrong.

1. **Baseline.** @@Actions/jev-baseline@@ runs Jev over past records that carry the
   LLM's label, with the same label definitions and a short description of the
   setting, into @@Datasets/jev_baseline@@. We measure agreement and Cohen's κ. If
   they agree close to 100% of the time, Jev can take over as is: we either go
   straight to step 4, or review a random sample in step 2 first. High agreement
   only says Jev does what the LLM does; the review measures how accurate both are,
   catches mistakes they make together, and can still show where Jev's instructions
   can be tightened.
2. **Annotate.** One annotator labels a blind sample in @@Tasks/adjudicate@@: the
   disagreements, spread over each kind (e.g. "LLM says X, Jev says Y"), plus a random
   sample; with near-total agreement, mostly the random sample. They choose among @@Assets/annotation-labels@@, which add UNCLEAR ("I could
   defend more than one answer"), following @@Assets/annotation-guidelines@@, and
   aren't shown either system's answer. About an hour, around 200 short texts; more
   for many labels or low agreement. The labels go to @@Datasets/adjudication@@.
3. **Improve.** From the annotations, find the mistakes Jev makes that the LLM
   doesn't, and the definitions the annotator found unclear. Add a sentence to Jev's
   instructions for each consistent pattern, and rerun with @@Actions/jev-rules@@
   into @@Datasets/jev_rules@@. Repeat with a new rules action if needed.
4. **Thresholds and export.** Estimate Jev's accuracy at each threshold from the
   annotations, choose a threshold per label, and export the configuration to
   `config/jev_config.json` for our system to run independently.
5. **Ongoing evaluation.** Periodically run @@Actions/jev-check@@ on recent records
   into @@Datasets/jev_check@@, compare its labels and confidence with the exported
   run, and annotate a random sample in @@Tasks/check-annotate@@
   (@@Datasets/check_annotations@@) to catch drift.

Scores on the records the rules were written from are optimistic; the random
sample gives the fairer figures.

## Jev

Jev answers a **state** (the text to classify) and typed **questions**, each with
free-text **instructions** and **criteria** (a short definition per answer). With
one label, it's a **yes/no** question and Jev returns the probability that the label
applies. With several exclusive labels, it's a **choice**: Jev returns the chosen
label, a probability for each, and its confidence in the choice. With several labels
that aren't exclusive, each gets a yes/no question.

A **threshold** is the probability a label needs before it's applied (yes/no), or the
confidence below which a chosen label isn't trusted and the system falls back to
something else (choice). The best threshold often differs by label: a rarer label
may do best at 0.8 rather than 0.5.

## Results

`scripts/jev_eval.py` scores the exported datasets.

| Measure | Baseline | With rules |
|---|---|---|
| Records | | |
| Agreement with the LLM, κ | | |
| Annotator chose Jev / LLM on disagreements | | — |
| Accuracy on the random sample: LLM / Jev | | |

## Rules

<!-- One bullet per sentence added to config/instructions_rules.txt, with the
pattern from the annotations that motivated it. -->

## Configuration

<!-- The exported configuration: model version, instructions file, and each
label's threshold with the estimated accuracy, precision and recall at it. -->

## Decisions needed

1. **Sign off the rules**: each is a business choice about a definition.
2. **The thresholds**, and the fallback below them for a choice: the current LLM,
   a default, or a person.
3. **Sending data to TypeSafe**: confirm the texts may be sent to its API.
4. **Switching over**: run Jev alongside the LLM for a while, logging both decisions
   and Jev's cost and latency, and switch when the live comparison matches.
5. **How often to check for drift**, and who annotates the check samples.

## Progress Log
<!-- Most recent first. Shared by Assistant and Coding Agent. -->

## Decision Log

- **The existing LLM is the reference**: measure agreement first, and use humans
  only where the systems disagree, plus a random sample. _Rationale: the question is
  whether Jev can take over the LLM's job, and gold sets mainly show that category
  definitions are vague._
- **Agreement isn't accuracy**: even when Jev and the LLM nearly always agree, a
  random sample is worth reviewing before export. _Rationale: both can make the same
  mistake, the accuracy is what the thresholds are chosen from, and the review can
  still improve Jev's instructions._
- **Annotation is economical**: about an hour, and training data only if a
  systematic Jev failure shows up that instructions can't fix. _Rationale: Jev only
  has to match or beat the LLM, and choosing thresholds needs far fewer labels than
  training._
- **Definitions may follow Jev's natural boundary**: "both defensible"
  disagreements are settled by a business choice, not re-annotation. _Rationale: the
  requirements are usually underspecified, and a consistent, calibrated boundary is
  worth more than an arbitrary one._
- **Business rules go in the instructions**: one sentence per rule. _Rationale: a
  rule moves only the records it covers, without training data._

# Evaluating an LLM Classifier

## Goal

A classification decision in our product is made by prompting an LLM, and it has
never been measured against people. This project produces that measurement: how often
the classifier agrees with settled human labels on its real traffic, and which labels
it confuses. It also produces the settled labels, to re-check every future prompt
change against, and a list of what to fix.

The classifier stays as it is. Replacing it is a separate decision, which this
measurement informs.

## Current system

<!-- Fill in: what the classifier decides and where its output is used. -->

| | |
|---|---|
| Decision | |
| Labels | @@Assets/classifier-labels@@ |
| Model and prompt version | |
| Volume | |
| Where the output goes, and what each kind of mistake costs | |
| Period sampled | |

## Approach

1. **Sample.** A random sample of the texts the classifier sees in production, with
   the context it sees, is published as @@Assets/eval-texts@@. A random sample makes
   the figures describe the classifier as it runs.
2. **The LLM's answers.** @@Actions/eval-llm@@ runs the classifier over the texts and
   saves its answers to @@Datasets/eval_llm@@, credited to the LLM, as one more
   annotator.
3. **Pilot.** The annotator labels 50 of the texts blind in @@Tasks/eval-pilot@@,
   following @@Assets/annotation-guidelines@@, into @@Datasets/eval_pilot@@. A
   debrief afterwards settles unclear definitions before the main round.
4. **Annotate.** The annotator labels all of the texts blind in
   @@Tasks/eval-annotate@@, into @@Datasets/eval_annotations@@, pressing ignore where
   more than one answer is defensible. Optionally, a second annotator labels 50 in
   @@Tasks/eval-second@@ (@@Datasets/eval_second@@), for agreement: it says how much
   of the classifier's apparent error is just people disagreeing.
5. **Review.** @@Tasks/eval-review@@ accepts the texts everyone agrees on and shows
   the rest with every answer side by side, people's and the LLM's. The settled
   labels go to @@Datasets/eval_gold@@.
6. **Compare.** @@Actions/eval-compare@@ merges the settled labels and the LLM's
   answers into @@Datasets/eval_compare@@, and @@Services/eval-dashboard@@ shows the
   texts where they differ and which labels the LLM confuses.

The settled labels are the reference for every prompt change: rerun the classifier
into a new dataset and compare it with them the same way.

## Results

| Measure | Value |
|---|---|
| Texts | |
| Agreement with the settled labels | |
| Agreement between annotators | |
| Texts reviewed: classifier right / annotator right / neither | |

## Mistakes and fixes

<!-- The most common confusions, what causes each (the classifier, the definitions,
or the data), and the prompt or guideline change proposed for it. -->

## Prompt changes

<!-- One row per prompt version compared with the settled labels. -->

| Version | Change | Agreement | Notes |
|---|---|---|---|
| current | — | | |

## Decisions needed

1. **The definitions** settled in the pilot debrief and the review: each is a
   business choice.
2. **Whether the agreement is good enough** for what the output is used for, given
   what each kind of mistake costs.
3. **Prompt changes**: which to ship, once compared with the settled labels.
4. **How often to repeat** the measurement on new traffic.

## Limitations

- One sample of traffic; the figures may not hold if traffic changes.
- A label the classifier rarely gives has few examples in a random sample.
- The settled labels reflect one annotator, plus the review.

## Progress Log
<!-- Most recent first. Shared by Assistant and Coding Agent. -->

## Decision Log

- **The LLM is one more annotator**: its answers go to a dataset of their own, and
  the built-in review and dashboard compare it with people. _Rationale: the platform
  already compares annotators; only running the LLM is specific to it._
- **Annotate blind, then review with every answer in view**: _Rationale: seeing the
  classifier's answer anchors the annotator; the review is where the answers belong
  side by side._
- **Pilot before the main round**: _Rationale: unclear definitions found after 300
  labels mean relabelling; found after 50, they mean a short debrief._
- **The settled labels are frozen**: prompt changes are compared with them, and
  confirmed on the next round's fresh sample. _Rationale: a moving reference makes
  every change look like progress, and fixes written from the review's own
  disagreements look better on it than on new traffic._

# Evaluating an LLM Classifier

## Goal

A classification decision in our product is made by prompting an LLM, and it has
never been measured against people. This project produces that measurement: the
classifier's accuracy, and each label's precision, recall and true rate across all
of its traffic, with confidence intervals. It also produces a frozen gold set to
re-score every future prompt change against, and a list of what to fix.

The classifier stays as it is. Replacing it is a separate decision, which this
measurement informs.

## Current system

<!-- Fill in: what the classifier decides and where its output is used. -->

| | |
|---|---|
| Decision | |
| Labels | @@Assets/annotation-labels@@ |
| Model and prompt version | |
| Volume | |
| Where the output goes, and what each kind of mistake costs | |
| Period sampled | |

## Approach

1. **Sample.** The classifier's past decisions over a recent period, with its raw
   label (before any transform downstream), are published as
   @@Assets/eval-records@@. @@Actions/eval-sample@@ draws a stratified random sample
   by that label: each label gets its share, with a minimum so rare labels can be
   measured. Every sampled record carries a weight that brings it back to its share
   of all traffic, so the figures describe the classifier as it runs, not the
   sample. The annotation tasks load only the blind texts in @@Assets/eval-blind@@;
   the classifier's labels and the weights are in @@Assets/eval-llm-labels@@.
2. **Pilot.** The annotator labels about 50 texts blind in @@Tasks/eval-pilot@@,
   following @@Assets/annotation-guidelines@@ and choosing from
   @@Assets/annotation-labels@@. A debrief afterwards settles unclear definitions
   before the main round; the labels go to @@Datasets/eval_pilot@@.
3. **Annotate.** The annotator labels the whole sample blind in
   @@Tasks/eval-annotate@@, into @@Datasets/eval_annotations@@. Optionally, a second
   annotator labels a random subset in @@Tasks/eval-second@@
   (@@Datasets/eval_second@@), for agreement: it says how much of the classifier's
   apparent error is just people disagreeing.
4. **Adjudicate.** Every text where an annotator and the classifier disagree, or an
   annotator chose UNCLEAR, is settled in @@Tasks/eval-adjudicate@@: each answer is
   shown side by side, credited to the classifier or the annotator who gave it. The
   reviewer follows @@Assets/adjudication-guidelines@@, and the settled labels go to
   @@Datasets/eval_adjudication@@.
5. **Score and report.** @@Actions/eval-score@@ reports accuracy, per-label
   precision and recall, and each label's rate as the classifier assigns it against
   its estimated true rate, with 95% intervals. The most common mistakes, with
   example texts, say what to change in the prompt.
6. **Keep the gold set.** The settled sample, saved as @@Assets/eval-gold@@, is the
   regression set: rerun the classifier on it after every prompt change and score
   the new answers against it with the same action.

## Results

| Measure | Value (95% interval) |
|---|---|
| Accuracy | |
| Agreement between annotators (kappa) | |
| Texts adjudicated: classifier right / annotator right / neither / unclear | |

| Label | Precision | Recall | Classifier's rate | True rate |
|---|---|---|---|---|
| | | | | |

## Mistakes and fixes

<!-- The most common mistakes, what causes each (the classifier, the definitions, or
the data), and the prompt or guideline change proposed for it. -->

## Prompt changes

<!-- One row per prompt version scored against the gold set. -->

| Version | Change | Accuracy | Notes |
|---|---|---|---|
| current | — | | |

## Decisions needed

1. **The definitions** settled in the pilot debrief and the adjudication: each is a
   business choice.
2. **Whether the accuracy is good enough** for what the output is used for, given
   what each kind of mistake costs.
3. **Prompt changes**: which to ship, once scored against the gold set.
4. **How often to repeat** the measurement on new traffic.

## Limitations

- One period of traffic; the figures may not hold if traffic changes.
- Recall of a rare label has a wide interval: its misses hide among the much larger
  set of texts given other labels.
- The gold set reflects one annotator, plus adjudication.

## Progress Log
<!-- Most recent first. Shared by Assistant and Coding Agent. -->

## Decision Log

- **Measure the classifier as it runs**: a stratified random sample weighted back to
  real traffic, scored on the classifier's raw output. _Rationale: an enriched sample
  scored unweighted misstates accuracy, and transforms downstream hide what the
  model actually said._
- **Annotate blind, then adjudicate with both answers in view**: _Rationale: seeing
  the classifier's answer anchors the annotator; adjudication is where both answers
  belong._
- **Pilot before the main round**: _Rationale: unclear definitions found after 300
  labels mean relabelling; found after 50, they mean a short debrief._
- **The gold set is frozen**: prompt changes are scored against it, and confirmed on
  the next round's fresh sample. _Rationale: a moving reference makes every change
  look like progress, and fixes written from the gold set's own mistakes score
  optimistically on it._

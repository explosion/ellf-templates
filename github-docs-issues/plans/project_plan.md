# NLP Project Plan: GitHub docs issue classifier

## Problem Statement
Predict whether a GitHub issue is about documentation, so docs issues can be labelled and routed to the people who write the docs without someone reading every new issue. Part of @@Projects/GitHub Docs Issues@@.

## Approach
One binary text classifier with a single label, `DOCUMENTATION`, trained with spaCy's `textcat_multilabel` component. Each issue gets a score between 0 and 1; issues above a threshold are treated as docs issues. A single label keeps annotation fast: one accept or reject per issue.

## Data
@@Assets/GitHub Issues@@: GitHub issues as JSONL, mostly titles, some with the body. The label and its definition are in @@Assets/Docs Issue Label@@, the guidelines in @@Assets/Docs Issue Guidelines@@.

## Annotation
Annotate in @@Tasks/docs-issues-annotate@@: accept if the issue is about documentation, reject if it isn't, ignore if you can't tell. Answers go to @@Datasets/docs-issues@@.

- Aim for about 600 answers before the first training run. In the template's sample issues, about one in three is about documentation.
- Rejected issues teach the model as much as accepted ones, so don't skip them.
- When an issue takes long to decide, note why. If the same doubt keeps coming up, add a rule to the guidelines and publish a new version.

## Training
@@Actions/train-docs-issues@@ trains on @@Datasets/docs-issues@@, holding back 20% of the answers for evaluation, and writes @@Assets/Docs Issue Classifier@@.

| Run | Answers | Accepted | Score (AUC) | F at 0.5 | Notes |
|---|---|---|---|---|
| 0.1.0 | | | | | |

The overall score for `textcat_multilabel` is the area under the ROC curve (AUC): how well the scores rank docs issues above the rest, at any threshold. The F-score for `DOCUMENTATION` is at the default threshold of 0.5.

## Evaluation
- Look at the AUC and the `DOCUMENTATION` precision and recall in the training results. With 20% of a few hundred answers, the evaluation set is small: differences of a few points between runs are noise.
- Read the issues the model gets wrong. Mistakes on issues the guidelines don't cover mean the guidelines need a rule; mistakes on clear cases mean the model needs more data.
- Before relying on the scores, annotate a separate evaluation set in its own task and dataset, so every run is measured on the same issues.

## Next steps
- Annotate more issues with the model's suggestions, using the trained model in a new `textcat` task, and retrain with a new version.
- Pick a threshold for the use case: high precision if docs issues are labelled automatically, high recall if a person checks the suggestions.

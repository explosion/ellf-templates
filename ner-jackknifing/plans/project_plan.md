# Finding NER Annotation Errors by Jackknifing

## Goal

Find and fix the errors in our named-entity annotations, @@Datasets/pii_gold@@, without
re-reviewing every text. A large annotated set always holds some errors: an entity
missed, a boundary off by a word, a label the guidelines changed after the text was
annotated. A model trained on the data learns them, and an evaluation set with them
scores the model against them. The outcome is a corrected dataset, a model trained on
it, and guidelines that settle the cases the review turned up.

## Approach

Jackknifing checks every text against a model that never saw it. Errors are rare and
inconsistent, so a model trained on the rest of the data mostly learns the
conventions and not the error. Where its prediction differs from the annotation, one
of the two is wrong, and that is the text worth a person's time. A model that saw the
text in training would have learned its error and agree with it.

Each round:

1. **Split.** @@Actions/Folds r1@@ splits the annotations into four folds, with a copy
   of every annotation in @@Datasets/jk-r1@@.
2. **Train.** @@Actions/Train r1 fold 1@@, @@Actions/Train r1 fold 2@@,
   @@Actions/Train r1 fold 3@@ and @@Actions/Train r1 fold 4@@ each train a model on
   three folds, as parallel jobs.
3. **Predict.** @@Actions/Predict r1 fold 1@@, @@Actions/Predict r1 fold 2@@,
   @@Actions/Predict r1 fold 3@@ and @@Actions/Predict r1 fold 4@@ run each model over
   the fold it didn't see. @@Actions/Import r1 fold 1@@, @@Actions/Import r1 fold 2@@,
   @@Actions/Import r1 fold 3@@ and @@Actions/Import r1 fold 4@@ save the predictions
   beside the annotations in @@Datasets/jk-r1@@.
4. **Review.** @@Tasks/Review r1 disagreements@@ shows only the texts where a
   prediction and its annotation differ, and accepts the rest. The answers go to
   @@Datasets/jk-r1-reviewed@@, which then holds every text.
5. **Repeat** with @@Datasets/jk-r1-reviewed@@ as the annotations and a new prefix,
   until the queue is mostly the models' mistakes.

Finally, @@Actions/Train corrected@@ trains the model on the last round's reviewed
dataset.

## Data and labels

<!-- Fill in: what the texts are, how many, the language, and what the labels are. -->

| | |
|---|---|
| Annotations | @@Datasets/pii_gold@@ |
| Guidelines | @@Assets/Annotation guidelines@@ |
| Texts | |
| Language | |
| Labels | PERSON, ORG, LOC, ADDRESS, ID |

## Reviewing

- Decide by the guidelines, not by which version looks more plausible. When the
  guidelines don't settle a case, settle it, write it down under Decisions, add it to
  the guidelines, and answer the same way from then on.
- The model's version is often right. A disagreement is evidence against the
  annotation as much as against the model.
- Expect clusters: the same kind of case comes up again and again (a court's name, an
  address split over two lines, a case number). Settling it once settles all of them.
- @@Services/Jackknife dashboard@@ shows which labels the disagreements are in before
  you start.

## Rounds

| Round | Annotations | Texts | Shown in review | Annotation corrected | Model was wrong | Notes |
|---|---|---|---|---|---|---|
| 1 | @@Datasets/pii_gold@@ | | | | | |

The number shown should fall each round. Stop when most of what the review shows are
the models' mistakes.

## Decisions

<!-- Record the guideline decisions the review leads to, with an example of each:
     where entities start and end, which label a borderline case gets, what isn't an
     entity. -->

## Next steps

- Train the final model with @@Actions/Train corrected@@ on the last round's reviewed
  dataset, and evaluate it on a held-out sample that went through the same rounds.
- Annotate new texts with the same guidelines. When enough have built up, run a round
  on them too.

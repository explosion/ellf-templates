# NLP Project Plan: Food ingredient extraction

## Problem Statement
Find every mention of a food ingredient in text, so they can be counted and compared, e.g. which ingredients people talk about more or less over time. Part of @@Projects/Food Ingredients@@.

## Approach
One named entity recognizer with a single label, `INGRED`. A list of ingredients wouldn't be enough: people write "chicken stock", "sweet red onions" or "the mock duck", and an ingredient list is never complete. Match patterns get annotation started, and the model learns to find ingredients the patterns don't cover.

Two models are trained from the same annotations:
- **A CPU model** (spaCy's default tok2vec pipeline): quick to train, used to check progress and to suggest entities in the optional correction round.
- **A transformer model** (`roberta-base`): the most accurate, trained on GPU. It's the one to use once the annotations are done.

## Data
@@Assets/Reddit Cooking Comments@@: comments from a cooking forum as JSONL. The label and its definition are in @@Assets/Food Ingredient Label@@, the guidelines in @@Assets/Food Ingredient Guidelines@@ and the match patterns in @@Assets/Food Ingredient Patterns@@.

## Annotation
Annotate in @@Tasks/food-ingredients-annotate@@: highlight every ingredient, with the patterns as suggestions. Annotations go to @@Datasets/food-ingredients@@.

- Aim for about 1,000 comments. Most comments are short, so this takes a few hours.
- Accept comments without ingredients too: they teach the model what isn't one.
- Keep notes on what's hard to decide (dish or ingredient? does "fresh" belong in the span?) and add the answers to the guidelines.

## Training
@@Actions/train-food-ingredients@@ trains the CPU model on @@Datasets/food-ingredients@@ and writes @@Assets/Food Ingredients NER@@. Run it after a few hundred annotations to check that the model is learning, and again once annotation is done.

@@Actions/train-food-ingredients-trf@@ trains the transformer model on the same dataset and writes @@Assets/Food Ingredients NER Transformer@@. It needs a GPU.

Both hold back 20% of the annotations for evaluation.

| Run | Model | Annotations | F | P | R | Notes |
|---|---|---|---|---|---|---|
| 0.1.0 | CPU | | | | | |
| 0.1.0 | transformer | | | | | |

## Evaluation
- Compare precision and recall: low precision means the model highlights things that aren't ingredients (often dishes), low recall that it misses ingredients (often rare ones or multi-word names).
- Look at the mistakes before annotating more. Mistakes on cases the guidelines don't settle mean the guidelines need a rule; mistakes on clear cases mean the model needs more examples like them.
- With 20% of about 1,000 comments, the evaluation set is small: differences of a point or two between runs are noise.

## Optional: correct the model's suggestions
Once the CPU model is trained, create the `food-ingredients-correct` task with @@Assets/Food Ingredients NER@@: it suggests the ingredients in new comments and annotators correct them, which is faster than highlighting from scratch. The corrections go to a new `food-ingredients-correct` dataset. Then train both models again on both datasets with a new version; the README has the commands.

## Optional: annotation dashboard
Once annotation is underway, create the `food-ingredients-dashboard` service for @@Datasets/food-ingredients@@: a live view of how many ingredients have been highlighted, annotations that conflict between annotators, and a table of every annotation. Check it before each training run, and look at the conflicts with the guidelines open: they show which rules need to be clearer.

## Next steps
- Run the transformer model over the full data and count ingredient mentions, e.g. per month.
- For new kinds of text, such as recipes or menus, annotate a few hundred of them, too: a model trained on forum comments may miss ingredients written differently.

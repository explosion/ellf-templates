# Highlighting food ingredients

You'll see one comment from a cooking forum at a time. Highlight every mention of a food ingredient with the `INGRED` label, then accept the comment. Comments without any ingredients are accepted with nothing highlighted: they teach the model just as much.

Some ingredients are already highlighted by match patterns. They're suggestions: remove the ones that are wrong and add the ones they missed.

## What to highlight

- **Ingredients**: produce, meat and fish, dairy, eggs, grains, bread and pasta, spices and herbs, oils, condiments and drinks used in cooking.
- **General terms** that stand for ingredients: "meat", "veggies", "spices", "herbs".
- **Named sauces and stocks**: "soy sauce", "bbq sauce", "fish sauce", "chicken stock".
- **The whole name**, including the words that say which kind: "ground beef", "yellow onions", "apple cider vinegar", "heavy cream".

## What not to highlight

- **Dishes and meals**: pizza, soup, lasagna, burger, cake. A dish is what you make, an ingredient is what goes into it.
- **A bare "sauce" or "dressing"** that doesn't say which one.
- **Quantities and preparation**: "two cups of", "chopped", "fried". Highlight just the ingredient: in "two cups of chopped onions", highlight "onions".
- **Brands, equipment and restaurants**.

## When you're unsure

If the same word is sometimes an ingredient and sometimes a dish (e.g. "chicken" in "roast a chicken"), highlight it when it's being cooked with or eaten as food, which is almost always. If a comment isn't about food at all or isn't in English, accept it with nothing highlighted, or use **ignore** if it's unreadable.

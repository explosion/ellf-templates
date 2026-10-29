# Labelling texts for a classifier evaluation

You're building the reference answers that an automated classifier will be measured
against. The texts were drawn from its real traffic. You won't see what the
classifier said, so judge each text on its own.

## How to answer

- **Pick the label the definitions call for.** Read the label definitions shown with
  each text and choose the one that fits, as if you were the only one deciding.
- **Use the text as shown.** It's what the classifier saw. If it doesn't give you
  enough to decide, that's an answer too: choose the label the definitions have for
  that case, or UNCLEAR if they have none.
- **Choose UNCLEAR when you could defend more than one label** under the definitions
  as written. These are useful: each one points at a definition that needs a
  decision, and they're settled later, with the classifier's answer in view.
- **Don't use UNCLEAR for texts you find hard but can still decide.** Pick the best
  label instead.
- **Skip broken texts** (empty, garbled, the wrong language for the task) with the
  ignore button.

## Noting patterns

Keep a short list of the kinds of text that made you hesitate, with an example of
each: jargon, texts that only make sense with more context, a business rule you
applied that the definitions don't state. After the pilot, these are used to tighten
the definitions.

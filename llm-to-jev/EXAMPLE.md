# Worked example: three recruiting classifiers

This template was generalized from a project that moved three LLM classifiers in a
recruiting product to Jev. They're described here to show what each step tends to
turn up and what the rules look like. None of their data or results are included.

| Classifier | Labels | Question type |
|---|---|---|
| Answer colour: how well a candidate's reply answers a screening question | GREEN, YELLOW, RED, NEEDS_CLARIFICATION | choice |
| Sentiment: whether a candidate's message is negative | NEGATIVE | yes/no |
| Note relevance: whether a recruiter's note holds a fact for the candidate's profile | KEEP | yes/no |

## What the steps showed

**Baseline.** Agreement with the LLM was high on all three. Jev's confidence tracked
agreement closely: records it was very sure about almost always agreed, and the
disagreements sat where it reported doubt. That is what makes a cut-off work.

**Context matters for confidence.** Many screening replies only make sense in the
conversation ("Which state?", a reply in another language). Adding the last few turns
of the conversation to each record raised agreement a little and grew the share of
records Jev was very confident about a lot. If your LLM sees context, give Jev the
same context.

**The systems make different errors.** For sentiment, the LLM over-read polite
declines as disappointment, and Jev over-read curt replies ("No please", "Wrong
person") as negative. Where they disagreed, the annotator sided with Jev more often
than with the LLM on all three classifiers.

**Most remaining disagreements were definitions, not model errors.** Each was settled
by one sentence in the instructions:

- *Answer colour:* "If the candidate is asked whether they have a document or item
  and asks how to get one or asks to be sent one, they don't have it: RED." A second
  rule, "a plain yes is GREEN", was tried and dropped: a "yes" to an either/or
  question doesn't say which.
- *Sentiment:* "A short no, a polite decline, a plain opt-out ('Stop', 'Unsubscribe')
  or a wrong-person reply is not NEGATIVE by itself; it is NEGATIVE only if the
  candidate also sounds upset."
- *Note relevance:* applications to a job are KEEP; languages count as skills; praise
  inside a job pitch is not an assessment; and a glossary of recruiter shorthand
  ("sub" is a submittal to a client; "Pay", "Bill" and "MU" are pay rate, bill rate
  and markup).

Each rule moved only the records it covered, and moved them to high confidence;
records it didn't cover hardly changed. No training data was needed for any of them.

**Thresholds.** A confidence cut-off of 0.7 worked for all three, with a small share
of records below it handed to a fallback. Raising it to 0.9 sent several times as
many, mostly ones whose labels already looked right. For the rare NEGATIVE label,
the probability needed to apply it is worth tuning on its own: just above 0.5 is
where Jev's curt-reply mistakes sat.

## Things to watch for

- **A rare label needs an enriched sample.** Negative messages were a small share of
  traffic, so the sample over-represented them and every figure was weighted back to
  the real rate (`meta.weight`).
- **Labels that feed a decision.** Answer colours were mapped to pass, fail or
  follow-up, so two colours could lead to the same decision. Score the decision as
  well as the label when that's what the product uses.
- **Bugs in how records are built.** Some replies had been paired with a question
  that hadn't been asked yet. With the conversation as context, Jev answered
  NEEDS_CLARIFICATION there, which showed up as disagreements but was a bug in the
  existing pipeline.
- **The reference may not be the production model.** One classifier wasn't deployed
  yet, so it was compared with an offline LLM labelling. Say so in the plan, and
  repeat the comparison against production in the shadow run.

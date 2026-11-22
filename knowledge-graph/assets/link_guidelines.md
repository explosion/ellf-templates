# Linking mentions to entries

Each question shows a passage with a mention marked `[[like this]]`, and one candidate
entry from the entity list: its name, other names and description. Answer **accept** if
the mention refers to that entry, **reject** if it doesn't.

- Judge by the passage, not only the name: the same name can belong to different
  entries.
- A mention can refer to more than one entry, and then you'll say yes to more than one
  candidate. It can also refer to none: then say no to every candidate.
- If none of the candidates is right but you know the list has the right entry, say no
  to every candidate, flag the question and say which entry in a comment. The evaluation
  counts these: without them, a right entry the search missed looks like NIL.
- The level to link at is set in the project's schema. Follow the notes below for each
  entity type.

## Second-round questions

After the first round is settled, some names are asked about again.

- **More candidates.** When every candidate for a name was rejected, the same kind of
  question comes back with candidates from a wider search. Answer it the same way,
  flagging it as above if none is right but the list has the right entry.
- **One mention at a time.** When a name was linked to more than one entry in a
  document, each mention of it is asked about on its own. The question says so ("This
  name was linked to more than one entry in the document"), and only that mention is
  marked. Answer for that mention only: the same name can mean one entry in one
  sentence and another in the next.

## Notes per entity type

<!-- Fill in: which level of the list to link to, and the look-alikes to watch for. -->

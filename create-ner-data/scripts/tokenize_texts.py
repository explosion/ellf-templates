"""Add spaCy tokens to a JSONL file of texts, as the panel's actions need.

Each line needs a "text"; "meta" is kept, and anything else is dropped. The
entities the models mark land on these tokens, and the review tasks show them,
so tokenize the texts once, here, and use the output for every step:

    pip install spacy
    python scripts/tokenize_texts.py texts.jsonl texts_tokenized.jsonl --lang en
"""

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("input", help="JSONL with a 'text' per line")
    parser.add_argument("output", help="Where to write the texts with their tokens")
    parser.add_argument("--lang", default="en", help="The texts' language, for spaCy's tokenizer")
    args = parser.parse_args()

    import spacy

    nlp = spacy.blank(args.lang)
    n = 0
    with open(args.input, encoding="utf8") as f, open(args.output, "w", encoding="utf8") as out:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            eg = json.loads(line)
            text = eg.get("text")
            if not isinstance(text, str) or not text.strip():
                raise SystemExit(f"Line {i} has no text")
            tokens = [
                {"text": t.text, "start": t.idx, "end": t.idx + len(t), "id": t.i, "ws": bool(t.whitespace_)}
                for t in nlp.make_doc(text)
            ]
            row = {"text": text, "tokens": tokens, "meta": eg.get("meta") or {}}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    print(f"Wrote {n} tokenized texts to {args.output}")


if __name__ == "__main__":
    main()

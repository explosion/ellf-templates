# Annotating entities in support tickets

You'll see one customer support ticket at a time. Highlight every mention of
the vendor's products and the details a support engineer would copy into the
tracker. The label definitions, with examples, are shown next to the labels.

## Labels

| Label | Mark | Example |
|---|---|---|
| `PRODUCT` | A named product in the Meridian suite | *Meridian Cloud* |
| `FEATURE` | A named capability inside a product | *CSV export*, *audit log* |
| `ERROR_CODE` | An error identifier, including HTTP statuses | *ERR-4032*, *HTTP 502* |
| `VERSION` | A release of the vendor's own software | *v4.0.2*, *2026.8.1* |
| `INTEGRATION` | A third-party service the product connects to | *Slack*, *Okta* |

On the pre-labelling task you'll see `ORG`, `MONEY` and `DATE` instead. Those
are suggested by a model: correct anything it got wrong and accept the rest.

## Boundary rules

- **Mark the shortest span that fully names the entity.** *Meridian Cloud*,
  not *the Meridian Cloud dashboard*.
- **Leave determiners out.** Annotate *billing portal*, not *the billing
  portal*.
- **Don't nest spans.** If a product name appears inside a feature name, mark
  it as `PRODUCT`.
- **Decide integrations by role, not by company.** "syncing to Spotify" is an
  `INTEGRATION`, "our team at Spotify" is the customer and isn't one of these
  labels.
- **Only mark the vendor's versions.** "Windows 11" or "Chrome 128" stays
  unmarked.

## When you're unsure

- Highlighted suggestions come from match patterns. They're usually right, but
  check the boundaries before you accept.
- If a ticket is in the wrong language, empty or not a support request, use
  **ignore** rather than **reject**.
- If you can't decide between two labels, pick the closer one. Disagreements
  between annotators are resolved in the review task.

# Ellf Templates

Each top-level directory is one Ellf project template, in the format the `ellf-template` skill exports and imports: a `README.md` that documents every resource, plus `plans/`, `recipes/`, `config/` and `assets/` as needed. Templates are written by exporting a project with `/ellf-template`; edit their wording by hand, but keep the directory structure and file names.

[`templates.json`](templates.json) is the source of truth for the list of templates. The list of templates in the [README](README.md) is made from it.

## Adding or updating a template

When a template directory is added, or its README changes what the template includes, update both places.

### 1. `templates.json`

A JSON list with one object per template, in the same order as the README, with new templates added at the end. Read the template's README to fill in the fields:

| Field | Value |
| --- | --- |
| `name` | The directory name, e.g. `helpdesk-routing`. |
| `title` | Title Case, from the README's `# Ellf Template: <title>` heading. |
| `description` | Two or three sentences: what the project does, then what the workflow covers. Plain text, no markdown. |
| `use_cases` | Reuse existing values where they fit: `Information Extraction`, `Text Classification`, `Relation Extraction`, `LLM Distillation`, `PDF Processing`, `Evaluation`. |
| `counts` | `tasks`, `actions`, `agents`, `services`: the number of sections under the README's Tasks, Actions, Agents and Services headings. `recipes`: custom recipe packages in `recipes/` (built-in recipes don't count). `plans`: the files in `plans/`. Include every key, with `0` where there are none. |
| `url` | `https://github.com/explosion/ellf-templates/tree/main/<name>` |
| `author` | Who made it, e.g. `Explosion`. Leave it out if unknown. |
| `sample_data` | `true` if `assets/input/` holds data to try the workflow with, otherwise `false`. |
| `api_keys` | The external services the template needs API keys for, by provider name (e.g. `Google AI`, `TypeSafe`), from the secrets under "What you need to provide". Leave it out if there are none. |

Format with 2-space indentation and a trailing newline.

### 2. The README list

Add or update the template's entry under "## Templates", in the same order as `templates.json`:

```markdown
### [<title>](<name>)

<description>

**Use cases:** Text Classification, Evaluation

| Tasks | Actions | Agents | Plans | Sample data | API keys |
| :---: | :---: | :---: | :---: | :---: | --- |
| 9 | 3 | 1 | 4 | ✓ | Google AI, TypeSafe |
```

- **Use cases:** `use_cases`, comma-separated, as plain text.
- The table has a column for each non-zero count, in the order Tasks, Actions, Agents, Services, Custom recipes (`recipes`), Plans.
- Then Sample data, with ✓ if `sample_data` is true, and API keys, with `api_keys` comma-separated. Leave either column out if it would be empty.

## Checks

- `python -m json.tool templates.json` passes, and every `name` has a directory with a `README.md`.
- The README has one entry per template, in the same order, matching `templates.json`.
- Every link in the README resolves.

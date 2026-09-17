# Test Generator

[![Tests](https://github.com/leviathan747/test-generator/actions/workflows/python-package.yml/badge.svg)](https://github.com/leviathan747/test-generator/actions/workflows/python-package.yml)
[![PyPI version](https://img.shields.io/pypi/v/test-generator.svg)](https://pypi.org/project/test-generator/)

Generates test and quiz PDFs from YAML question banks via LaTeX (`pdflatex`).

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
pytest -q
```

## Installation

Install from source:

```bash
python -m pip install --upgrade build
python -m build
python -m pip install dist/test_generator-0.2.0-py3-none-any.whl
```

## Usage

### Command line

Generation is driven by one or more YAML config files, each describing an
assessment (generated in sequence):

```bash
python -m test_generator config.yaml [config2.yaml ...] \
  --questions questions.yaml \
  --out-dir output/ \
  --figures-dir path/to/figures
```

| Flag | Description |
|------|-------------|
| `--questions` | YAML file containing the question bank (optional, repeatable; combined with any `questions` list in the config file) |
| `--figures-dir` | Directory containing figures copied into the PDF build environment (optional, repeatable; on filename collisions the earliest-listed directory wins; default: current directory) |
| `--out-dir` | Directory where generated PDFs are written (default: current directory, created if missing) |
| `--from-manifest` | Recreate an existing version from its manifest file; provide the config (and `--questions`/`--figures-dir`) as in a normal run (see below) |
| `--new-version` | With `--from-manifest`: reissue the manifest's questions as a fresh version — new form ID, re-scrambled question and choice order, new manifest |
| `--exclude-manifest` | Drop the questions recorded in this manifest from the pool, so a follow-up assessment reuses none of them (repeatable; matched by question `id` only, no MD5 check). Cannot be combined with `--from-manifest` |
| `--report-from-manifest` | Print the coverage/DOK report recorded in a manifest and exit; standalone — takes no config files, generates nothing |
| `--report` | Print a section-coverage and DOK report after each generation (see below) |
| `--archive` | Also write a self-contained `<class_id>_<name>_<form_id>.zip` for long-term storage (see below). Cannot be combined with `--watch` |
| `--watch` | Watch the config file(s), questions file(s), and figures directories for changes and regenerate drafts automatically (the footer shows `draft` in place of a form ID; no manifest is written) |
| `--student-only` | With `--watch`: regenerate only the student copy, for faster iteration (default: both copies). Not valid outside watch mode |
| `--solution-only` | With `--watch`: regenerate only the solution copy, for faster iteration (default: both copies). Not valid outside watch mode |

#### Config file

```yaml
name: Quiz_1.3
title: "Quiz 1.3: Estimating Limit Values From Graphs"
author: Levi Starrett
class_name: AP Calculus AB
class_id: APCalc
duration: 10 min
sections: 1.3 - 1.7
assessment_type: quiz
```

| Key | Description |
|-----|-------------|
| `name` | Assessment name, used in the output filename (defaults to the config file's basename) |
| `class_id` | Optional class identifier; if set, output filenames are prefixed with `<class_id>_` |
| `title` | Test title |
| `author` | Author name |
| `class_name` | Class name |
| `duration` | Duration string (e.g. `30 min`) |
| `instructions` | Optional raw LaTeX rendered in a framed box at the top of the first page |
| `assessment_type` | Optional filter: keep only questions whose `assessment_type` matches |
| `sections` | Optional filter: a section range (see below) |
| `calculator_active` | Optional filter: `true` keeps only calculator-active questions, `false` keeps only no-calculator questions; a question missing the field counts as no-calculator |
| `question_count` | Optional: randomly select exactly this many questions from the filtered pool (see below); errors if fewer questions match the filters |
| `dok_target` | Optional: steer the selection's average DOK to at least — and as close as possible to — this target (see below) |
| `scramble_questions` | Optional: `true` shuffles the order of the selected questions (default `false`, keeping question-bank order) |
| `questions` | Optional list of questions, in the same format as the questions file |
| `work_space` | Default height of the FRQ answer work space (e.g. `2in`); questions and parts can override it with their own `work_space` field (default: `1in`) |

Questions come from the `--questions` file(s), the config file's `questions`
list, or all combined (file questions first). This allows a simple
assessment to be generated from a single self-contained file:

```yaml
name: Quiz_1.3
class_id: APCalc
questions:
  - id: 1
    question: What is $2 + 2$?
    answer: 4
    distractors: [3, 5]
    solution: Because $2+2=4$.
```

#### Question fields

| Key | Description |
|-----|-------------|
| `id` | Required. Identifier used for manifest lookup; must be unique across the included questions |
| `question` | The question stem (LaTeX) |
| `question_type` | `MCQ` (default) or `FRQ`; compared case-insensitively |
| `answer` | The correct MCQ choice |
| `distractors` | The incorrect MCQ choices |
| `solution` | The worked solution shown in the solution copy (LaTeX) |
| `parts` | Sub-parts of a multipart FRQ; a part may carry its own `question`, `solution`, `sections`, `dok`, `grading`, `work_space`, and figure fields |
| `sections` | Standards covered, as `major.minor` values; non-numeric tokens (e.g. `unknown`) are tolerated and skipped |
| `dok` | Depth of Knowledge, typically 1-4; a non-integer marker counts as unrecorded. A multipart question without its own `dok` is rated by its hardest part |
| `calculator_active` | Whether a calculator is permitted for this question |
| `assessment_type` | Free-form filter tag (e.g. `quiz`, `test`) |
| `related_to` | Ids of related questions, to avoid selecting them together |
| `grading` | Rubric entries (see below) |
| `work_space` | FRQ answer-space height (LaTeX length, e.g. `2in`) |
| `figure`, `figure_placement`, `figure_width` | Figure to show with the question (see below) |
| `legacy_ids` | Historical identifiers; editorial metadata, ignored by the generator |
| `review` | Editorial workflow marker; ignored by the generator |

#### Question selection and the report

When `question_count` is set, that many questions are chosen at random
from the pool of questions matching the filters. Selection maximizes the
number of unique sections covered, and questions linked by a
`related_to` field are not chosen together unless the pool is too small
to satisfy `question_count` otherwise. When `dok_target` is set, a
best-effort swap pass then nudges the selection's average DOK to at
least the target, as close to it as the pool allows. Selected questions
keep their question-bank order unless `scramble_questions: true`.
Selection and scrambling re-randomize on every run (including `--watch`
draft regeneration); use the manifest to recreate a specific version.

With `--report`, a report is printed after each generation showing a
histogram of the number of questions covering each section, a histogram
of DOK levels (a multipart question is rated by its hardest part), and
the average DOK of the selected questions. When a `dok_target` is set,
the average is shown against it and highlighted in yellow if the target
was missed. When the `sections` filter is a bounded range (e.g.
`1.1 - 1.16`), every section in the range is listed, even with zero
questions, so coverage gaps stand out; DOK levels 1-4 are always listed.

Because manifests record each question's sections and DOK,
`--report-from-manifest <manifest.yaml>` prints the same report for an
existing version on its own — no config, question bank, or figures
needed, and nothing is regenerated. (Version-1 manifests predate the
embedded report data; replay those with `--from-manifest ... --report`
instead.)

The solution copy also prints each question's DOK, sections, and id
beside its solution, for review.

#### Form IDs and manifests

Each run mints a fresh form ID — 8 random hex characters — that is printed
(grouped, e.g. `3f9a-1c2e`) in the bottom-left page footer and used
(ungrouped) in the manifest filename. Output files are written to the output
directory as `<class_id>_<name>.pdf` (student copy),
`<class_id>_<name>_solutions.pdf` (solution copy), and
`<class_id>_<name>_<form_id>.manifest.yaml` (the version manifest); without
a `class_id` the `<class_id>_` prefix is dropped. Re-runs
overwrite the PDFs but mint a new ID, so manifests accumulate side by side
and any prior version can still be recreated from its manifest.

The manifest records everything needed to recreate that exact version: the
MD5 digests of the input files (config, question bank(s), and referenced
figures), the question IDs in presentation order, and the order in which
each MCQ's answer choices were shown. It also records each question's
sections and DOK, each MCQ's answer letter, and a top-level `answer_key`
summary string.

Rerunning with the same config plus `--from-manifest <manifest.yaml>`
(and `--questions`/`--figures-dir` if the original run used them)
regenerates the same printed pages — same questions, order, choices, and
form ID — recreating deleted PDFs or overwriting existing ones. The input
files may have moved since generation; they are matched against the
manifest by content (MD5), not by path. If a loaded file's digest doesn't
appear in the manifest — or a manifest entry matches no loaded file — the
tool reports the mismatches and asks for confirmation before continuing.

A replay writes a manifest of its own. Because a plain replay reuses the
original form ID, that manifest lands on the original's path, so the tool
asks before overwriting it. If the config now asks for more questions
than the manifest holds, the manifest's questions are kept and the normal
picker tops up the remainder (the added questions are exempt from MD5
verification).

Adding `--new-version` turns a replay into a fresh version of the same
test: the manifest's questions are reused, but with a new form ID and
re-scrambled question and choice order (scrambling happens regardless of
the config's `scramble_questions`), recorded in its own new manifest.

#### Archives

`--archive` writes `<class_id>_<name>_<form_id>.zip` next to the PDFs and
manifest (which are still written, and `--report` still prints) for normal
runs and replays. It holds everything needed to recreate that version under
a single `<class_id>_<name>_<form_id>/` folder:

- `README.md` — the coverage/DOK report, the generator command that
  replays the version from the archived files, and `pdflatex` commands
- the manifest
- the config file and question bank(s) (under `questions/`), pruned to the
  selected questions; kept questions are copied byte-for-byte, and banks
  contributing no questions are left out
- only the referenced figures (under `figures/`)
- `<class_id>_<name>.tex` and `<class_id>_<name>_solutions.tex`, which
  build the PDFs with `pdflatex` alone, without the generator

The archived manifest matches the standalone one (same form ID, timestamp,
questions, and answer key) except for its `files` MD5 sums, which describe
the pruned copies. Rebuilt PDFs match in content but not byte-for-byte,
since `pdflatex` embeds the build time.

#### Figures

A question (or an individual part of a multipart FRQ) can float a figure
to the right of its content with the optional `figure` field:

```yaml
questions:
  - id: 1
    question: Use the graph of $y = f(x)$ to find $\lim_{x \to -4^+} f(x)$.
    figure: 27.tex
    figure_width: 2.5in
    answer: 4
    distractors: [3, 5]
```

The value is a filename inside a figures directory, extension included
(a bare `27` would be parsed as a number). `.tex` files (standalone
TikZ documents) are included with `\input`; any other extension is
included with `\includegraphics`. The figure keeps its natural size and
the question text — and, for MCQs, the answer choices — flows in the
remaining width to its left; the solution box stays full width below.
The optional `figure_width` accepts any LaTeX length (e.g. `2.5in`,
`0.4\linewidth`) and rescales the figure when it is too large. A figure
too wide to leave a usable text column falls back to full width below
the text.

The optional `figure_placement` field chooses where the figure goes:

- `right` (the default) — floated to the right as described above.
- `above` — centered above the question, before the question number so
  the number stays aligned with the question text.
- `below` — centered below the question text; for MCQs it sits between
  the text and the answer choices, and for FRQs between the text and
  the solution space (for a multipart FRQ stem, before the parts).

All placements keep the figure with its question across page breaks.

Questions may instead embed figures as raw LaTeX in the question text
(e.g. `\fullwidth{\begin{center}\input{figures/27.tex}\end{center}}`
for a full-width centered figure), but don't combine that `\fullwidth`
escape with the `figure` field on the same question.

#### Grading rubrics

A question (or an individual part of a multipart FRQ) can carry a
grading rubric in the optional `grading` field — a list of entries with
a numerical `points` value and a `criterion` string:

```yaml
questions:
  - id: 1
    question: Evaluate $\lim_{x \to 2} h(x)$.
    question_type: FRQ
    solution: The limit is 12.
    grading:
      - points: 1
        criterion: Correct limit statement
      - points: 1
        criterion: Factor and cancel
      - points: 1
        criterion: Answer
```

When `grading` is present, the summed points are appended to the
question text in bold parentheses (e.g. `(3 points)`), and the solution
copy shows the rubric as a braced points/criterion list to the right of
the solution. A rubric too wide to leave a usable solution column is
placed flush right below the solution instead. Point values and
criteria are not written manually in the question or solution text.

#### Section filtering

The `sections` config key filters questions by their `sections` metadata
using SemVer-style version ranges, except section numbers have no patch
component (they are `major.minor`, e.g. `1.3`). A question without parts
is included only when the highest section it lists falls within the
range. For multipart FRQs, the highest section listed on each part must
fall within the range (question-level sections are ignored). When either
filter is set, questions missing the corresponding field are excluded.
The `calculator_active` filter differs: questions missing the field are
treated as `calculator_active: false` rather than excluded.

Supported range syntax:

| Range | Meaning |
|-------|---------|
| `1.3` | exactly section 1.3 |
| `1.3 - 1.7` | 1.3 through 1.7, inclusive |
| `>=1.3 <1.8` | comparators (`<`, `<=`, `>`, `>=`, `=`); all must hold |
| `1.3 \|\| 2.1` | alternatives; any may match |
| `1.x` / `1.*` | any section in unit 1 |
| `*` | any section |
| `^1.3` | `>=1.3 <2.0` |
| `~1.3` | `>=1.3 <1.4` |

Note: YAML parses bare `X.10` as the number `X.1`, so quote section
numbers with a trailing zero (e.g. `sections: ['1.10']`) in question
files.

### Schemas

Config files, question banks, and manifests are validated at load time against
JSON Schemas (Draft 2020-12) bundled in
[`test_generator/schemas/`](test_generator/schemas):

- `question.schema.json` — a single question (MCQ or FRQ), its `parts`, and
  `grading` entries. Used for both question-bank files and a config's inline
  `questions` list.
- `config.schema.json` — a test/quiz config file (its `questions` reference the
  question schema).
- `manifest.schema.json` — a generated manifest artifact (accepts versions
  1–3).

The schemas are strict: an unknown or misspelled key is rejected with an error
naming the field and source file. To validate ad hoc, use
`test_generator.validation.validate_config` / `validate_questions` /
`validate_manifest`.

### Python API

```python
import test_generator

test_generator.generate_test(
    "questions.yaml",             # path, sequence of paths, or None
    "output.pdf",
    title="Unit 1: Limits and Continuity",
    author="Levi Starrett",
    class_name="AP Calculus AB",
    form_id="3f9a-1c2e",          # printed in the page footer
    duration="30 min",
    figures_dir="path/to/figures",  # path or sequence of paths; defaults to
                                  # figures/ next to the first YAML file
    solution=False,               # True renders the answer-key copy
    assessment_type="quiz",       # optional question filter
    sections="1.3 - 1.7",         # optional section range filter
    calculator_active=False,      # optional calculator filter; False keeps
                                  # only no-calculator questions
    questions=None,               # optional list of question mappings appended
                                  # to those loaded from the YAML file (which
                                  # may be None when questions are passed here)
    work_space=None,              # default FRQ work-space height
    question_order=None,          # optional list of question ids fixing the
                                  # presentation order
    choice_orders=None,           # optional {question id: permutation} fixing
                                  # each MCQ's answer-choice order
    instructions="",              # optional raw LaTeX instruction box
)
```

Also exported: `filter_questions`, `select_questions`, `load_question_pool`,
`make_choice_orders`, and `format_report` — the building blocks the CLI uses
to go from a question bank to a selected, ordered set and its report.

## Publishing

Create a Git tag `v0.2.0` and push; the repository's publish workflow will upload to PyPI when configured with `PYPI_API_TOKEN` secret.

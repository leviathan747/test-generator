# Test Generator

[![Tests](https://github.com/leviathan747/test-generator/actions/workflows/python-package.yml/badge.svg)](https://github.com/leviathan747/test-generator/actions/workflows/python-package.yml)
[![PyPI version](https://img.shields.io/pypi/v/test-generator.svg)](https://pypi.org/project/test-generator/)

A tiny Python package skeleton that demonstrates a test-generator utility.

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
| `--questions` | YAML file containing the question bank (optional; combined with any `questions` list in the config file) |
| `--from-manifest` | Recreate an existing version from its manifest file; provide the config (and `--questions`/`--figures-dir`) as in a normal run (see below) |
| `--out-dir` | Directory where generated PDFs are written (default: current directory, created if missing) |
| `--figures-dir` | Directory containing figures copied into the PDF build environment (default: current directory) |
| `--watch` | Watch the config file(s), questions file, and figures directory for changes and regenerate drafts automatically (the footer shows `draft` in place of a form ID; no manifest is written) |
| `--student-only` | Generate only the student copy (default: both copies) |
| `--solution-only` | Generate only the solution copy (default: both copies) |

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
| `class_id` | Class identifier, used in the output filename (required) |
| `title` | Test title |
| `author` | Author name |
| `class_name` | Class name |
| `duration` | Duration string (e.g. `30 min`) |
| `assessment_type` | Optional filter: keep only questions whose `assessment_type` matches |
| `sections` | Optional filter: a section range (see below) |
| `calculator_active` | Optional filter: `true` keeps only calculator-active questions, `false` keeps only no-calculator questions; a question missing the field counts as no-calculator |
| `question_count` | Optional: randomly select exactly this many questions from the filtered pool (see below); errors if fewer questions match the filters |
| `scramble_questions` | Optional: `true` shuffles the order of the selected questions (default `false`, keeping question-bank order) |
| `questions` | Optional list of questions, in the same format as the questions file |
| `work_space` | Default height of the FRQ answer work space (e.g. `2in`); questions and parts can override it with their own `work_space` field (default: `1in`) |

Questions come from the `--questions` file, the config file's `questions`
list, or both combined (file questions first). This allows a simple
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

#### Question selection and the report

When `question_count` is set, that many questions are chosen at random
from the pool of questions matching the filters. Selection maximizes the
number of unique sections covered, and questions linked by a
`related_to` field are not chosen together unless the pool is too small
to satisfy `question_count` otherwise. Selected questions keep their
question-bank order unless `scramble_questions: true`. Selection and
scrambling re-randomize on every run (including `--watch` draft
regeneration); use the manifest to recreate a specific version.

After each generation a report is printed showing a histogram of the
number of questions covering each section, a histogram of DOK levels
(a multipart question is rated by its hardest part), and the average
DOK of the selected questions. When the `sections` filter is a bounded
range (e.g. `1.1 - 1.16`), every section in the range is listed, even
with zero questions, so coverage gaps stand out; DOK levels 1-4 are
always listed.

#### Form IDs and manifests

Each run mints a fresh form ID — 8 random hex characters — that is printed
(grouped, e.g. `3f9a-1c2e`) in the bottom-left page footer and used
(ungrouped) in the manifest filename. Output files are written to the output
directory as `<class_id>_<name>.pdf` (student copy),
`<class_id>_<name>_solutions.pdf` (solution copy), and
`<class_id>_<name>_<form_id>.manifest.yaml` (the version manifest). Re-runs
overwrite the PDFs but mint a new ID, so manifests accumulate side by side
and any prior version can still be recreated from its manifest.

The manifest records everything needed to recreate that exact version: the
MD5 digests of the input files (config, question bank, and referenced
figures), the question IDs in presentation order, and the order in which
each MCQ's answer choices were shown. Rerunning with the same config plus
`--from-manifest <manifest.yaml>` (and `--questions`/`--figures-dir` if the
original run used them) regenerates the same printed pages — same questions,
order, choices, and form ID — recreating deleted PDFs or overwriting
existing ones. The input files may have moved since generation; they are
matched against the manifest by content (MD5), not by path. If a loaded
file's digest doesn't appear in the manifest — or a manifest entry matches
no loaded file — the tool reports the mismatches and asks for confirmation
before continuing. No new manifest is written on reproduce; the existing
one remains the record for that form ID.

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

The value is a filename inside the figures directory, extension included
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

### Python API

```python
import test_generator

test_generator.generate_test(
    "questions.yaml",
    "output.pdf",
    title="Unit 1: Limits and Continuity",
    author="Levi Starrett",
    class_name="AP Calculus AB",
    form_id="3f9a-1c2e",           # printed in the page footer
    duration="30 min",
    figures_dir="path/to/figures",  # optional; defaults to figures/ next to the YAML file
    solution=False,               # True renders the answer-key copy
    assessment_type="quiz",       # optional question filter
    sections="1.3 - 1.7",         # optional section range filter
    calculator_active=False,      # optional calculator filter; False keeps
                                  # only no-calculator questions
    questions=None,               # optional list of question mappings appended
                                  # to those loaded from the YAML file (which
                                  # may be None when questions are passed here)
)
```

## Publishing

Create a Git tag `v0.1.0` and push; the repository's publish workflow will upload to PyPI when configured with `PYPI_API_TOKEN` secret.

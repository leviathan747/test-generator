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
python -m pip install dist/test_generator-0.1.0-py3-none-any.whl
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
| `--out-dir` | Directory where generated PDFs are written (default: current directory, created if missing) |
| `--figures-dir` | Directory containing figures copied into the PDF build environment (default: a `figures/` subdirectory next to the questions file) |
| `--watch` | Watch the config file(s), questions file, and figures directory for changes and regenerate automatically |
| `--student-only` | Generate only the student copy (default: both copies) |
| `--solution-only` | Generate only the solution copy (default: both copies) |

#### Config file

```yaml
name: Quiz_1.3
title: "Quiz 1.3: Estimating Limit Values From Graphs"
author: Levi Starrett
class_name: AP Calculus AB
class_id: APCalc
form_id: A
duration: 10 min
sections: 1.3 - 1.7
assessment_type: quiz
```

| Key | Description |
|-----|-------------|
| `name` | Assessment name, used in the output filename (defaults to the config file's basename) |
| `class_id` | Class identifier, used in the output filename (required) |
| `form_id` | Form identifier (e.g. `A`, `B`), used in the output filename and on the test (required) |
| `title` | Test title |
| `author` | Author name |
| `class_name` | Class name |
| `duration` | Duration string (e.g. `30 min`) |
| `assessment_type` | Optional filter: keep only questions whose `assessment_type` matches |
| `sections` | Optional filter: a section range (see below) |
| `questions` | Optional list of questions, in the same format as the questions file |

Questions come from the `--questions` file, the config file's `questions`
list, or both combined (file questions first). This allows a simple
assessment to be generated from a single self-contained file:

```yaml
name: Quiz_1.3
class_id: APCalc
form_id: A
questions:
  - id: 1
    question: What is $2 + 2$?
    answer: 4
    distractors: [3, 5]
    solution: Because $2+2=4$.
```

Output files are written to the output directory as
`<class_id>_<name>_Form<form_id>.pdf` (student copy) and
`<class_id>_<name>_Form<form_id>_solutions.pdf` (solution copy).

#### Section filtering

The `sections` config key filters questions by their `sections` metadata
using SemVer-style version ranges, except section numbers have no patch
component (they are `major.minor`, e.g. `1.3`). A question without parts
is included only when the highest section it lists falls within the
range. For multipart FRQs, the highest section listed on each part must
fall within the range (question-level sections are ignored). When either
filter is set, questions missing the corresponding field are excluded.

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
    form_id="A",
    duration="30 min",
    figures_dir="path/to/figures",  # optional; defaults to figures/ next to the YAML file
    solution=False,               # True renders the answer-key copy
    assessment_type="quiz",       # optional question filter
    sections="1.3 - 1.7",         # optional section range filter
    questions=None,               # optional list of question mappings appended
                                  # to those loaded from the YAML file (which
                                  # may be None when questions are passed here)
)
```

## Publishing

Create a Git tag `v0.1.0` and push; the repository's publish workflow will upload to PyPI when configured with `PYPI_API_TOKEN` secret.

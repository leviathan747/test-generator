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

```bash
python -m test_generator input.yaml output.pdf \
  --title "Unit 1: Limits and Continuity" \
  --author "Levi Starrett" \
  --class-name "AP Calculus AB" \
  --form-id A \
  --duration "30 min" \
  --images-dir path/to/images
```

All options are optional and default to an empty string (or `None` for `--images-dir`).

| Flag | Description |
|------|-------------|
| `--title` | Test title |
| `--author` | Author name |
| `--class-name` | Class name |
| `--form-id` | Form identifier (e.g. `A`, `B`) |
| `--duration` | Duration string (e.g. `30 min`) |
| `--images-dir` | Directory containing images copied into the PDF build environment. Defaults to an `images/` subdirectory next to the YAML file. |

### Python API

```python
import test_generator

test_generator.generate_test(
    "input.yaml",
    "output.pdf",
    title="Unit 1: Limits and Continuity",
    author="Levi Starrett",
    class_name="AP Calculus AB",
    form_id="A",
    duration="30 min",
    images_dir="path/to/images",  # optional; defaults to images/ next to the YAML file
)
```

## Publishing

Create a Git tag `v0.1.0` and push; the repository's publish workflow will upload to PyPI when configured with `PYPI_API_TOKEN` secret.

# Test Generator

[![Tests](https://github.com/leviathan747/test-generator/actions/workflows/python-package.yml/badge.svg)](https://github.com/leviathan747/test-generator/actions/workflows/python-package.yml)
[![PyPI version](https://img.shields.io/pypi/v/test-generator.svg)](https://pypi.org/project/test-generator/)

A tiny Python package skeleton that demonstrates a test-generator utility.

## Installation

Install from source:

```bash
python -m pip install --upgrade build
python -m build
python -m pip install dist/test_generator-0.1.0-py3-none-any.whl
```

Run tests:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Usage

### Command line

```bash
python -m test_generator input.yaml output.pdf \
  --title "Unit 1: Limits and Continuity" \
  --author "Levi Starrett" \
  --class-name "AP Calculus AB" \
  --form-id A \
  --duration "30 min"
```

All options are optional and default to an empty string.

| Flag | Description |
|------|-------------|
| `--title` | Test title |
| `--author` | Author name |
| `--class-name` | Class name |
| `--form-id` | Form identifier (e.g. `A`, `B`) |
| `--duration` | Duration string (e.g. `30 min`) |

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
)
```

## Publishing

Create a Git tag `v0.1.0` and push; the repository's publish workflow will upload to PyPI when configured with `PYPI_API_TOKEN` secret.

# Test Generator

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

```python
import test_generator

print(test_generator.__version__)
print(test_generator.generate_test("example"))
# -> test_example
```

## Publishing

Create a Git tag `v0.1.0` and push; the repository's publish workflow will upload to PyPI when configured with `PYPI_API_TOKEN` secret.

# test-generator

Generates test/quiz PDFs from YAML question banks via LaTeX (`pdflatex`).

## Python style

- All Python code must be PEP 8 compliant in style (naming, indentation,
  whitespace, imports grouped stdlib/third-party/local).
- All Python code must use type hints: annotate every function signature
  (parameters and return type, including `-> None` and test functions) and
  any variable whose type can't be inferred (e.g. empty list/dict/set
  literals).
- Target Python 3.10+: use built-in generics (`list[str]`, `dict[str, Any]`)
  and `X | None` unions, not `typing.List`/`Optional`.
- A question mapping loaded from YAML is typed as `Question`
  (`test_generator.core.Question`); reuse it rather than writing
  `dict[str, Any]` for questions.
- Keep the code mypy-clean: run `python3 -m mypy test_generator/ tests/`
  after changes.

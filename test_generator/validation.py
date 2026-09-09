"""JSON Schema validation for configs, questions, and manifests.

Schemas are bundled under ``test_generator/schemas`` and loaded once into a
``referencing`` registry so cross-file ``$ref``s resolve. Each ``validate_*``
helper raises a ``RuntimeError`` describing the first violation, matching the
error style used elsewhere in the package.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

_CONFIG_ID = "https://roxsoftware.com/test-generator/schemas/config.schema.json"
_QUESTION_ID = (
    "https://roxsoftware.com/test-generator/schemas/question.schema.json"
)
_MANIFEST_ID = (
    "https://roxsoftware.com/test-generator/schemas/manifest.schema.json"
)

# Schema filename keyed by its ``$id`` URI.
_SCHEMA_FILES = {
    _QUESTION_ID: "question.schema.json",
    _CONFIG_ID: "config.schema.json",
    _MANIFEST_ID: "manifest.schema.json",
}


@lru_cache(maxsize=None)
def _registry() -> Registry:
    """Build a registry containing every bundled schema, keyed by ``$id``."""
    resources_dir = resources.files(__package__).joinpath("schemas")
    resources_by_id: list[tuple[str, Resource[Any]]] = []
    for schema_id, filename in _SCHEMA_FILES.items():
        schema = json.loads(resources_dir.joinpath(filename).read_text())
        resources_by_id.append((schema_id, Resource.from_contents(schema)))
    return Registry().with_resources(resources_by_id)


@lru_cache(maxsize=None)
def _validator(schema_id: str) -> Draft202012Validator:
    """Return a cached validator for the schema with the given ``$id``."""
    registry = _registry()
    schema = registry.contents(schema_id)
    return Draft202012Validator(schema, registry=registry)


def _location(error: ValidationError) -> str:
    """Render the JSON path to the offending value, or 'top level'."""
    if not error.absolute_path:
        return "top level"
    return "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    ).lstrip(".")


def _validate(schema_id: str, instance: Any, source: str) -> None:
    """Validate ``instance`` and raise RuntimeError on the first error."""
    validator = _validator(schema_id)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.absolute_path)
    if errors:
        error = errors[0]
        raise RuntimeError(
            f"Schema validation failed for {source} at {_location(error)}: "
            f"{error.message}"
        )


def validate_config(config: dict[str, Any], source: str) -> None:
    """Validate a loaded config mapping."""
    _validate(_CONFIG_ID, config, source)


def validate_questions(questions: list[dict[str, Any]], source: str) -> None:
    """Validate each question in a loaded pool."""
    for index, question in enumerate(questions):
        qid = question.get("id", index) if isinstance(question, dict) else index
        _validate(_QUESTION_ID, question, f"{source} (question {qid!r})")


def validate_manifest(manifest: dict[str, Any], source: str) -> None:
    """Validate a loaded manifest mapping."""
    _validate(_MANIFEST_ID, manifest, source)

"""Contract validation against JSON Schema 2020-12 using referencing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMAS_DIR = Path(__file__).parent / "schemas"
SCHEMA_NAMES = (
    "common",
    "forcing-config",
    "scenario",
    "run-manifest",
    "reach-row",
    "gauge-row",
    "state-response",
)


class ContractError(ValueError):
    def __init__(self, message: str, path: list | None = None):
        super().__init__(message)
        self.message = message
        self.path = list(path) if path is not None else []

    def __str__(self) -> str:
        if self.path:
            return f"{self.message} at {self.path}"
        return self.message


def _load_registry_and_schemas() -> tuple[Registry, dict[str, dict[str, Any]]]:
    registry = Registry()
    schemas: dict[str, dict[str, Any]] = {}
    for name in SCHEMA_NAMES:
        path = SCHEMAS_DIR / f"{name}.schema.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        schemas[name] = data
        resource = Resource.from_contents(data, default_specification=DRAFT202012)
        schema_id = data.get("$id")
        if schema_id:
            registry = registry.with_resource(schema_id, resource)
        registry = registry.with_resource(f"{name}.schema.json", resource)
    return registry, schemas


_REGISTRY, _SCHEMAS = _load_registry_and_schemas()


def validate_json(schema_name: str, obj: Any) -> None:
    norm_name = schema_name.removesuffix(".schema.json")
    if norm_name not in _SCHEMAS:
        raise ValueError(f"Unknown schema name: {schema_name}")
    schema = _SCHEMAS[norm_name]
    validator = jsonschema.Draft202012Validator(schema=schema, registry=_REGISTRY)
    try:
        validator.validate(obj)
    except jsonschema.ValidationError as err:
        path = list(err.absolute_path)
        raise ContractError(err.message, path=path) from err

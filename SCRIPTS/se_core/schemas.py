"""Schema loading and validation.

``jsonschema`` is a required runtime dependency for validation. If it is missing,
validation functions raise a clear RuntimeError instead of silently passing.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from .paths import load_json, repo_root, tree_fingerprint

try:  # pragma: no cover - exercised through HAVE_JSONSCHEMA
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import SchemaError

    HAVE_JSONSCHEMA = True
except Exception:  # pragma: no cover
    Draft202012Validator = None
    FormatChecker = None
    SchemaError = Exception
    HAVE_JSONSCHEMA = False


def _build_format_checker():
    """A stdlib-only format checker so date/date-time are enforced without extras."""
    checker = FormatChecker()

    @checker.checks("date-time")
    def _is_date_time(value):
        if not isinstance(value, str):
            return True
        try:
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    @checker.checks("date")
    def _is_date(value):
        if not isinstance(value, str):
            return True
        try:
            datetime.date.fromisoformat(value)
            return True
        except ValueError:
            return False

    return checker


FORMAT_CHECKER = _build_format_checker() if HAVE_JSONSCHEMA else None


def schema_index(root=None) -> dict:
    root = Path(root) if root else repo_root()
    return load_json(root / "SCHEMAS" / "index.json")


_SCHEMA_CACHE: dict = {}
_SCHEMA_CACHE_MAX = 4


def load_schemas(root=None) -> dict:
    """Load and return every schema declared by ``SCHEMAS/index.json``.

    Memoized on the ``SCHEMAS`` tree fingerprint only: the root path is irrelevant
    because two roots with identical SCHEMAS content produce the same fingerprint.
    This allows tmp roots (copied from the canon) to share the cached schemas,
    avoiding a ~65ms fingerprint per unique tmp root on DrvFs.
    """
    root = Path(root) if root else repo_root()
    fp = tree_fingerprint(root, ("SCHEMAS",))
    cached = _SCHEMA_CACHE.get(fp)
    if cached is not None:
        return cached
    index = schema_index(root)
    schemas = {}
    for name, rel in index["schemas"].items():
        schemas[name] = load_json(root / rel)
    if len(_SCHEMA_CACHE) >= _SCHEMA_CACHE_MAX:
        _SCHEMA_CACHE.clear()
    _SCHEMA_CACHE[fp] = schemas
    return schemas


def validate(instance, schema) -> list:
    """Return a list of human-readable validation errors (empty means valid)."""
    if not HAVE_JSONSCHEMA:
        raise RuntimeError(
            "jsonschema is required for validation but is not installed. "
            "Install it with: python -m pip install jsonschema"
        )
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    messages = []
    for err in errors:
        location = "/".join(str(p) for p in err.path) or "<root>"
        messages.append(f"{location}: {err.message}")
    return messages


def check_schema(schema) -> None:
    """Raise SchemaError if the schema is not a valid JSON Schema."""
    if not HAVE_JSONSCHEMA:
        raise RuntimeError("jsonschema is required but is not installed")
    Draft202012Validator.check_schema(schema)

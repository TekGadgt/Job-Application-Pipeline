"""Helpers shared by the agent stages."""
from __future__ import annotations

import re

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _fill(template: str, **values: object) -> str:
    """Brace-safe template fill: values may contain literal { } freely.

    Single-pass substitution over the template only — placeholder-like text
    inside inserted values is never itself substituted, and the prompts'
    literal JSON braces ({"title": ...}) don't match the identifier pattern.
    """
    return _PLACEHOLDER_RE.sub(
        lambda m: str(values.get(m.group(1), m.group(0))), template
    )

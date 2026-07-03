"""Helpers shared by the agent stages."""
from __future__ import annotations


def _fill(template: str, **values: object) -> str:
    """Brace-safe template fill: values may contain literal { } freely."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out

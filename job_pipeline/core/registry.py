"""Name -> class registries: the extensibility seam for stages/sources/seeders."""
from __future__ import annotations

_STAGES: dict[str, type] = {}
_SOURCES: dict[str, type] = {}
_SEEDERS: dict[str, type] = {}


def _make_pair(table: dict[str, type], kind: str):
    def register(name: str):
        def deco(cls: type) -> type:
            table[name] = cls
            return cls
        return deco

    def get(name: str) -> type:
        try:
            return table[name]
        except KeyError:
            raise KeyError(
                f"unknown {kind} {name!r}; known: {sorted(table)}"
            ) from None
    return register, get


register_stage, get_stage = _make_pair(_STAGES, "stage")
register_source, get_source = _make_pair(_SOURCES, "source")
register_seeder, get_seeder = _make_pair(_SEEDERS, "seeder")

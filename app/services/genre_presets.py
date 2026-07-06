"""
L2 re-export: genre_presets moved to L0 (app.core.genre_presets) — it's pure data.
This shim keeps `from app.services.genre_presets import ...` working for any
old caller.
"""
from app.core.genre_presets import (
    GENRE_PRESETS,
    SUBGENRE_PRESETS,
    PLATFORM_PRESETS,
    list_genres,
    list_genre_names,
    list_subgenre_names,
    list_platforms,
    parse_genre_string,
    parse_subgenre_string,
    serialize_genres,
    serialize_subgenres,
    genre_to_keywords,
    genre_id_to_name,
    genre_name_to_id,
)

__all__ = [
    "GENRE_PRESETS",
    "SUBGENRE_PRESETS",
    "PLATFORM_PRESETS",
    "list_genres",
    "list_genre_names",
    "list_subgenre_names",
    "list_platforms",
    "parse_genre_string",
    "parse_subgenre_string",
    "serialize_genres",
    "serialize_subgenres",
    "genre_to_keywords",
    "genre_id_to_name",
    "genre_name_to_id",
]

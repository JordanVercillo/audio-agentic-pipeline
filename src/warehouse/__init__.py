"""
warehouse — Medallion Architecture Data Transforms
====================================================
Implements Staging → Cleansed → Modeled data warehouse layers.

Usage:
    from src.warehouse import (
        land_staging,
        build_cleansed,
        build_modeled,
        load_fact_table,
        load_dimension,
    )
"""

from .staging import land_staging_tracks, land_staging_features, land_staging_artists
from .cleansed import build_cleansed_tracks, build_cleansed_features, build_cleansed_artists
from .modeled import (
    build_star_schema,
    load_fact_table,
    load_dimension,
)

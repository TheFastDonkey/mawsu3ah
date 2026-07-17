"""Helpers for linking names (authors, editors, publishers) to their works.

The multi-creator refactor stores these names as NameRecord M2M relations,
so slug annotations are no longer needed; prefetch the related NameRecords
and read their `.slug` attribute directly.
"""

"""Declarative base with the naming convention of file 05 §3.

The convention is fixed before the first migration so constraint names are
identical in every environment. CHECK constraints are always given an explicit
name (the column they constrain), producing ``ck_<table>_<column>``.
"""

from enum import StrEnum

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Tier(StrEnum):
    """File 05 header: how a table is treated (audited, updated in place, or rebuilt)."""

    AUTHORED = "authored"
    REGISTRY = "registry"
    DERIVED = "derived"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def tier(value: Tier) -> dict[str, Tier]:
    """Table ``info`` payload carrying the tier label every model must have."""
    return {"tier": value}

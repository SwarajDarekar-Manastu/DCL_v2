"""Alembic environment for the DCL schema (file 05 §3).

Autogenerate compares tables, columns, FKs, uniques and plain indexes. It never manages
the objects that live only in hand-written migrations: HNSW and BM25 indexes (named with
the ``hnsw_`` / ``bm25_`` prefixes) and CHECK constraints (Alembic does not compare those).

The ParadeDB image ships extensions that own tables (PostGIS ``spatial_ref_sys``, the tiger
geocoder and topology schemas on the search path). Only tables in the current schema that
no extension owns are compared; everything an extension owns is left alone.
"""

import os

from alembic import context
from sqlalchemy import create_engine, pool, text

import backend.postgres.models  # noqa: F401  registers every table on Base.metadata
from backend.postgres.base import Base

HAND_WRITTEN_INDEX_PREFIXES = ("hnsw_", "bm25_")

OWN_TABLES_SQL = text(
    """
    SELECT c.relname
    FROM pg_class AS c
    WHERE c.relnamespace = current_schema()::regnamespace
      AND c.relkind IN ('r', 'p')
      AND NOT EXISTS (
          SELECT 1 FROM pg_depend AS d
          WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
      )
    """
)


def database_url() -> str:
    url = os.environ.get("DCL_DATABASE_URL")
    if not url:
        raise RuntimeError("DCL_DATABASE_URL is not set")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def include_name_for(own_tables: set[str]):
    def include_name(name, type_, parent_names):
        if type_ == "table":
            return name in own_tables or name in Base.metadata.tables
        return True

    return include_name


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and name and name.startswith(HAND_WRITTEN_INDEX_PREFIXES):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=Base.metadata,
        include_object=include_object,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        own_tables = set(connection.execute(OWN_TABLES_SQL).scalars())
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            include_name=include_name_for(own_tables),
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

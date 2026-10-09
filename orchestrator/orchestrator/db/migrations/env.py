"""Alembic environment.

Two things worth knowing. The URL comes from settings rather than alembic.ini,
so no connection string is ever committed. And autogenerate is scoped to schema
`app`: the LangGraph checkpointer creates and owns its own tables in the default
schema, and Alembic must never try to manage or drop them.
"""

from logging.config import fileConfig

from alembic import context
from orchestrator.config import get_settings
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

APP_SCHEMA = "app"
target_metadata = None


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Anything outside schema `app` belongs to somebody else."""
    if type_ == "table":
        return getattr(obj, "schema", None) == APP_SCHEMA
    return True


def _url() -> str:
    return get_settings().alembic_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=include_object,
        version_table_schema=APP_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {APP_SCHEMA}")
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table_schema=APP_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from core.config import settings


def get_checkpointer():
    """
    Returns an async context manager that yields a ready-to-use
    AsyncPostgresSaver connected to the app's Postgres instance.

    Usage:
        async with get_checkpointer() as checkpointer:
            ...
    """

    # psycopg (used directly here, not through SQLAlchemy) needs a plain
    # postgresql:// URI — SQLAlchemy's "+psycopg" driver suffix isn't valid
    # in a raw psycopg connection string.
    psycopg_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    return AsyncPostgresSaver.from_conn_string(psycopg_url)

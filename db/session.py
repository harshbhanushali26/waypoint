"""
db/session.py
 
Async SQLAlchemy engine + session factory for Waypoint's application tables
(trips, itineraries). This is deliberately separate from the LangGraph
checkpointer's own connection (AsyncPostgresSaver.from_conn_string in
db/checkpointer.py) - same Postgres instance, two independent connection
paths, matching the "single instance, two roles" split from the
architecture doc.
 
Uses psycopg (async) rather than asyncpg, to stay consistent with the driver
already resolved for the checkpointer in Step 2, rather than introducing a
second async Postgres driver into the project.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from core.config import settings


engine = create_async_engine(
    settings.database_url,
    echo=False,                 # flip to True temporarily if you need to see raw SQL
    pool_pre_ping=True,         # guards against stale connections after idle periods
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False, # keep ORM objects usable after commit, since finalize_node returns right after committing
)
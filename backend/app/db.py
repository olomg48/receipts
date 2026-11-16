from functools import lru_cache
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session


class Base(DeclarativeBase):
    pass


class DatabaseNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _engine_for_url(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return _engine_for_url(database_url)


def get_db_session():
    with Session(get_engine()) as session:
        yield session


def check_database_connection() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))

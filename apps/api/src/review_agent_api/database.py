"""Database setup. Source code is deliberately never emitted from this module."""

from collections.abc import Generator
from os import getenv

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


load_dotenv(override=False)


def database_url() -> str:
    """Get a safe local default while production receives its URL from the environment."""
    return getenv("DATABASE_URL", "sqlite:///./review_agent.db")


class Database:
    def __init__(self, url: str | None = None) -> None:
        resolved_url = url or database_url()
        connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(resolved_url, future=True, connect_args=connect_args)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Generator[Session, None, None]:
        with self.sessions() as session:
            yield session

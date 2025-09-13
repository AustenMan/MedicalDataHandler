from __future__ import annotations


import logging
import os
from contextlib import contextmanager
from typing import Generator, Optional, TYPE_CHECKING


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session


from mdh_app.database.models import Base


if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


# Global state for database engine and session management
_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker] = None
_SCOPED_SESSION = None


def init_engine(db_path: str, echo: bool = False) -> None:
    """Initialize SQLAlchemy engine and create tables."""
    global _ENGINE, _SESSION_FACTORY, _SCOPED_SESSION

    if _ENGINE is not None:
        return

    if not db_path:
        raise ValueError("Database path cannot be empty")

    # Ensure parent directory exists
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Create SQLite connection URI
    uri = f"sqlite:///{db_path}"

    # Configure engine with SQLite optimizations
    _ENGINE = create_engine(
        uri,
        echo=echo,
        connect_args={
            "check_same_thread": False,  # Allow multi-threading
        },
    )

    # Create all tables defined in models
    Base.metadata.create_all(_ENGINE)

    # Configure session factory
    _SESSION_FACTORY = sessionmaker(
        bind=_ENGINE, 
        expire_on_commit=False
    )
    _SCOPED_SESSION = scoped_session(_SESSION_FACTORY)

@contextmanager
def get_session(expire_all: bool = False) -> Generator[Session, None, None]:
    """Provide database session with automatic transaction handling.
    
    Args:
        expire_all: If True, expire all objects in session to force fresh DB reads.
    """
    if _ENGINE is None:
        raise RuntimeError(
            "Database engine not initialized. Call init_engine(db_path) first."
        )

    session: Session = _SCOPED_SESSION()  # type: ignore[call-arg]
    try:
        if expire_all:
            session.expire_all()  # Force fresh reads from database
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        _SCOPED_SESSION.remove()

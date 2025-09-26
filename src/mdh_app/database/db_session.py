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
    
    If `expire_all` is True use a brand-new Session (no cached identity map).
    Otherwise use the scoped session for normal operations.
    """
    if _ENGINE is None:
        raise RuntimeError("Database engine not initialized. Call init_engine(db_path) first.")

    use_scoped = not expire_all and _SCOPED_SESSION is not None
    session: Session
    
    try:
        # Re-use scoped session for normal ops
        if use_scoped:
            session = _SCOPED_SESSION()
        # Otherwise make a fresh session to avoid cached objects
        else:
            session = _SESSION_FACTORY()

        # If needed to expire, ensure the identity map is cleared
        if expire_all:
            session.expire_all()

        yield session
        session.commit()
    
    except Exception:
        session.rollback()
        logger.exception("Session rollback because of exception", exc_info=True, stack_info=True)
        raise
    
    finally:
        # Close the session instance
        try:
            session.close()
        finally:
            # Only remove the scoped registry if we used it
            if use_scoped:
                _SCOPED_SESSION.remove()

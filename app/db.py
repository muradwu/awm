from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

# строка подключения как у тебя было (оставь свою)
SQLALCHEMY_DATABASE_URL = "sqlite:///./awm.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # для SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ВАЖНО: импортируем модели, чтобы они зарегистрировались в Base.metadata
from ..models import Base  # type: ignore

def init_db():
    """
    Создаёт недостающие таблицы (idempotent).
    Вызывать на старте приложения или вручную.
    """
    # Критично: убедиться, что все модели импортированы
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

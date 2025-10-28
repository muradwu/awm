from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# --- Конфигурация БД ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./awm.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # для SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI routes"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Создаёт недостающие таблицы. Импортирует модели только внутри функции,
    чтобы избежать циклического импорта.
    """
    from app.models import Base  # импорт внутри функции, не вверху
    Base.metadata.create_all(bind=engine)

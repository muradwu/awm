from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# --- Конфигурация базы данных ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./awm.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # только для SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI routes"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Инициализация таблиц ---
from app.models import Base  # абсолютный импорт (работает и локально, и на Render)

def init_db():
    """Создаёт все таблицы, если их нет."""
    import app.models  # убедиться, что все модели зарегистрированы
    Base.metadata.create_all(bind=engine)

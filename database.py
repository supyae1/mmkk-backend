import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# On Render / Supabase, set DATABASE_URL in env, e.g.:
# postgres://user:password@host:5432/dbname
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

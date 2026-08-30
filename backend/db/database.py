import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.db_models import Base

# Defaults to a local SQLite file so you can run this with zero setup during
# the hackathon. Swap DATABASE_URL to your Postgres connection string
# (e.g. postgresql://user:pass@localhost:5432/codelens) when you're ready —
# no code changes needed elsewhere.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./codelens.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON, Index
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def gen_id() -> str:
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    source = Column(String, nullable=False)       # "upload" or "github_url"
    source_ref = Column(String, nullable=True)     # original URL or filename
    status = Column(String, default="processing")  # processing | ready | failed
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(String, primary_key=True, default=gen_id)
    # index=True speeds up every per-project query in structure, docs, diagram
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    path = Column(String, nullable=False)
    language = Column(String, nullable=True)
    symbols = Column(JSON, nullable=True)   # functions/classes extracted
    imports = Column(JSON, nullable=True)   # internal/external deps
    created_at = Column(DateTime, default=datetime.utcnow)


class Explanation(Base):
    __tablename__ = "explanations"

    id = Column(String, primary_key=True, default=gen_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    file_path = Column(String, nullable=False)
    level = Column(String, nullable=False)  # beginner | developer | technical
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class GeneratedArtifact(Base):
    """Stores generated docs and diagrams so /history can list them."""
    __tablename__ = "generated_artifacts"

    id = Column(String, primary_key=True, default=gen_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # "readme" | "api_docs" | "diagram"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Chunk(Base):
    """
    A chunk of source code used for semantic search ("Ask Your Codebase").

    embedding is stored as a JSON list of floats so this works on SQLite with
    zero extra dependencies.  When you switch to Postgres+pgvector, replace
    the JSON column with:
        from pgvector.sqlalchemy import Vector
        embedding = Column(Vector(384), nullable=True)
    and add an HNSW index for fast ANN search.
    """
    __tablename__ = "chunks"

    id = Column(String, primary_key=True, default=gen_id)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    file_path = Column(String, nullable=False)
    chunk_text = Column(Text, nullable=False)
    # JSON list[float] on SQLite; swap for pgvector.Vector on Postgres
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

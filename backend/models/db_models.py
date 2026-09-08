import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Index,
)
from sqlalchemy.orm import declarative_base


Base = declarative_base()


def gen_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    username = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=gen_id)

    user_id = Column(
        String,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    name = Column(String(255), nullable=False)

    source = Column(
        String(50),
        nullable=False,
    )  # upload | github_url

    source_ref = Column(
        String(1000),
        nullable=True,
    )

    status = Column(
        String(30),
        default="processing",
        nullable=False,
    )  # processing | ready | failed

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(String, primary_key=True, default=gen_id)

    project_id = Column(
        String,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )

    path = Column(
        String(1000),
        nullable=False,
    )

    language = Column(
        String(50),
        nullable=True,
    )

    symbols = Column(
        JSON,
        nullable=True,
    )

    imports = Column(
        JSON,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Explanation(Base):
    __tablename__ = "explanations"

    id = Column(String, primary_key=True, default=gen_id)

    project_id = Column(
        String,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )

    file_path = Column(
        String(1000),
        nullable=False,
    )

    level = Column(
        String(30),
        nullable=False,
    )  # beginner | developer | technical

    content = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"

    id = Column(String, primary_key=True, default=gen_id)

    project_id = Column(
        String,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )

    kind = Column(
        String(50),
        nullable=False,
    )
    # readme
    # api_docs
    # diagram

    content = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String, primary_key=True, default=gen_id)

    project_id = Column(
        String,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )

    file_path = Column(
        String(1000),
        nullable=False,
    )

    chunk_text = Column(
        Text,
        nullable=False,
    )

    embedding = Column(
        JSON,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=gen_id)

    user_id = Column(
        String,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    project_id = Column(
        String,
        ForeignKey("projects.id"),
        nullable=True,
        index=True,
    )

    action = Column(
        String(100),
        nullable=False,
    )

    details = Column(
        JSON,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


Index(
    "ix_project_files_project_path",
    ProjectFile.project_id,
    ProjectFile.path,
)

Index(
    "ix_explanations_project_file_level",
    Explanation.project_id,
    Explanation.file_path,
    Explanation.level,
)

Index(
    "ix_artifacts_project_kind",
    GeneratedArtifact.project_id,
    GeneratedArtifact.kind,
)

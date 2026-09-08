import io
import logging
import os
import re
import subprocess
import tempfile
import zipfile
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from db.database import SessionLocal, get_db
from models.db_models import Chunk, Project, ProjectFile
from services.ai_client import embed_text
from services.audit import log_action
from services.parser import EXT_TO_LANG, chunk_file, parse_project
from services.user_service import get_or_create_default_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Extracted uploads live here while the project is being analyzed.
STORAGE_ROOT = os.getenv(
    "CODELENS_STORAGE_ROOT",
    os.path.join(tempfile.gettempdir(), "codelens_projects"),
)
os.makedirs(STORAGE_ROOT, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024

_ALLOWED_GIT_URL = re.compile(
    r"^https://(github\.com|gitlab\.com|bitbucket\.org)/[\w.\-]+/[\w.\-]+(\.git)?/?$",
    re.IGNORECASE,
)


def _safe_upload_filename(filename: str) -> str:
    filename = (filename or "uploaded_code").replace("\\", "/")
    filename = os.path.basename(filename)
    filename = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip(" .")
    return filename or "uploaded_code"


def _is_zip_payload(filename: str, raw: bytes) -> bool:
    if filename.lower().endswith(".zip"):
        return True
    return zipfile.is_zipfile(io.BytesIO(raw))


def _mark_failed_and_raise(
    db: Session,
    project: Project,
    status_code: int,
    detail: str,
) -> None:
    project.status = "failed"
    db.commit()
    raise HTTPException(status_code, detail)


def _extract_zip_safely(
    zip_path: str,
    repo_path: str,
    db: Session,
    project: Project,
) -> None:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            total_uncompressed = sum(
                item.file_size for item in zf.infolist()
            )

            if total_uncompressed > MAX_UPLOAD_BYTES * 10:
                _mark_failed_and_raise(
                    db,
                    project,
                    400,
                    "Zip contents exceed the allowed decompressed size.",
                )

            real_root = os.path.realpath(repo_path)

            for member in zf.infolist():
                target = os.path.realpath(
                    os.path.join(repo_path, member.filename)
                )

                if os.path.commonpath(
                    [real_root, target]
                ) != real_root:
                    _mark_failed_and_raise(
                        db,
                        project,
                        400,
                        "Zip contains unsafe path traversal entries.",
                    )

            zf.extractall(repo_path)

    except zipfile.BadZipFile:
        _mark_failed_and_raise(
            db,
            project,
            400,
            "Uploaded file is not a valid zip archive.",
        )


def _run_parse_job(project_id: str, repo_path: str) -> None:
    """
    Parse files, extract symbols, chunk code for search, and store embeddings.
    Runs after the upload response is sent.
    """
    db = SessionLocal()

    try:
        project = (
            db.query(Project)
            .filter(Project.id == project_id)
            .first()
        )

        if not project:
            logger.error(
                "Parse job: project %s not found.",
                project_id,
            )
            return

        try:
            parsed_files = parse_project(repo_path)

            if not parsed_files:
                project.status = "failed"
                db.commit()

                logger.warning(
                    "Parse job found no supported files for project %s.",
                    project_id,
                )
                return

            for parsed_file in parsed_files:
                db.add(
                    ProjectFile(
                        project_id=project_id,
                        path=parsed_file["path"],
                        language=parsed_file["language"],
                        symbols=parsed_file["symbols"],
                        imports=parsed_file["imports"],
                    )
                )

            for parsed_file in parsed_files:
                chunks = chunk_file(
                    parsed_file["full_path"],
                    parsed_file["symbols"],
                )

                for chunk_text in chunks:
                    try:
                        embedding = embed_text(chunk_text)

                    except Exception:
                        logger.warning(
                            "Embedding failed for %s in project %s; "
                            "storing chunk without embedding.",
                            parsed_file["path"],
                            project_id,
                        )
                        embedding = None

                    db.add(
                        Chunk(
                            project_id=project_id,
                            file_path=parsed_file["path"],
                            chunk_text=chunk_text,
                            embedding=embedding,
                        )
                    )

            project.status = "ready"
            db.commit()

            logger.info(
                "Parse job complete for project %s.",
                project_id,
            )

        except Exception:
            db.rollback()

            project = (
                db.query(Project)
                .filter(Project.id == project_id)
                .first()
            )

            if project:
                project.status = "failed"
                db.commit()

            logger.exception(
                "Parse job failed for project %s.",
                project_id,
            )

    finally:
        db.close()


@router.post("/upload", status_code=201)
@router.post("/projects", status_code=201, include_in_schema=False)
async def upload_project(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    github_url: Optional[str] = Form(None),
):
    if not file and not github_url:
        raise HTTPException(
            400,
            "Provide either a code file, zip file, or github_url.",
        )

    if file and github_url:
        raise HTTPException(
            400,
            "Provide only one of: file, github_url.",
        )

    # ---------------------------------------------------------
    # FILE / ZIP UPLOAD
    # ---------------------------------------------------------
    if file:
        raw = await file.read(MAX_UPLOAD_BYTES + 1)

        if not raw:
            raise HTTPException(
                400,
                "Uploaded file is empty.",
            )

        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413,
                f"Upload exceeds the "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )

        filename = _safe_upload_filename(
            file.filename or "uploaded_code"
        )

        is_zip = _is_zip_payload(filename, raw)

        if not is_zip:
            extension = os.path.splitext(filename)[1].lower()

            if extension not in EXT_TO_LANG:
                supported = ", ".join(sorted(EXT_TO_LANG))

                raise HTTPException(
                    400,
                    f"Unsupported file type "
                    f"'{extension or 'none'}'. "
                    f"Supported: {supported}",
                )

        project_name = (
            os.path.splitext(filename)[0]
            if is_zip
            else filename
        )

        # Get or create the default user.
        user = get_or_create_default_user(db)

        # Create the project and associate it with the user.
        project = Project(
            user_id=user.id,
            name=project_name,
            source="upload",
            source_ref=filename,
        )

        db.add(project)
        db.commit()
        db.refresh(project)

        # Record project creation in audit log.
        log_action(
            db=db,
            action="UPLOAD_PROJECT",
            user_id=user.id,
            project_id=project.id,
            details={
                "source": project.source,
                "source_ref": project.source_ref,
            },
        )

        repo_path = os.path.join(
            STORAGE_ROOT,
            project.id,
        )

        os.makedirs(
            repo_path,
            exist_ok=True,
        )

        if is_zip:
            zip_path = os.path.join(
                STORAGE_ROOT,
                f"{project.id}.zip",
            )

            try:
                with open(zip_path, "wb") as fh:
                    fh.write(raw)

                _extract_zip_safely(
                    zip_path,
                    repo_path,
                    db,
                    project,
                )

            finally:
                if os.path.exists(zip_path):
                    os.remove(zip_path)

        else:
            target_path = os.path.realpath(
                os.path.join(
                    repo_path,
                    filename,
                )
            )

            real_root = os.path.realpath(repo_path)

            if os.path.commonpath(
                [real_root, target_path]
            ) != real_root:
                _mark_failed_and_raise(
                    db,
                    project,
                    400,
                    "Invalid upload filename.",
                )

            with open(target_path, "wb") as fh:
                fh.write(raw)

    # ---------------------------------------------------------
    # GITHUB / GITLAB / BITBUCKET URL
    # ---------------------------------------------------------
    else:
        if not _ALLOWED_GIT_URL.match(github_url or ""):
            raise HTTPException(
                400,
                "github_url must be a public HTTPS URL "
                "on github.com, gitlab.com, or bitbucket.org.",
            )

        name = (
            github_url
            .rstrip("/")
            .split("/")[-1]
            .replace(".git", "")
        )

        # Get or create the default user.
        user = get_or_create_default_user(db)

        # Create the project and associate it with the user.
        project = Project(
            user_id=user.id,
            name=name,
            source="github_url",
            source_ref=github_url,
        )

        db.add(project)
        db.commit()
        db.refresh(project)

        # Record project creation in audit log.
        log_action(
            db=db,
            action="project_created",
            user_id=user.id,
            project_id=project.id,
            details={
                "source": "github_url",
                "source_ref": github_url,
            },
        )

        repo_path = os.path.join(
            STORAGE_ROOT,
            project.id,
        )

        try:
            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    github_url,
                    repo_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

        except FileNotFoundError:
            _mark_failed_and_raise(
                db,
                project,
                500,
                "git is not installed on this server.",
            )

        except subprocess.TimeoutExpired:
            _mark_failed_and_raise(
                db,
                project,
                504,
                "git clone timed out after 60 seconds.",
            )

        if result.returncode != 0:
            _mark_failed_and_raise(
                db,
                project,
                400,
                f"git clone failed: {result.stderr[:300]}",
            )

    # ---------------------------------------------------------
    # BACKGROUND PARSING
    # ---------------------------------------------------------
    background_tasks.add_task(
        _run_parse_job,
        project.id,
        repo_path,
    )

    # ---------------------------------------------------------
    # RESPONSE
    # ---------------------------------------------------------
    return {
        "project_id": project.id,
        "name": project.name,
        "status": project.status,
        "source": project.source,
    }


@router.get("/upload/{project_id}/status")
@router.get(
    "/projects/{project_id}/status",
    include_in_schema=False,
)
def get_status(
    project_id: str,
    db: Session = Depends(get_db),
):
    project = (
        db.query(Project)
        .filter(Project.id == project_id)
        .first()
    )

    if not project:
        raise HTTPException(
            404,
            "Project not found.",
        )

    return {
        "project_id": project.id,
        "status": project.status,
    }

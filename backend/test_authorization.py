"""Focused ownership tests for project-scoped backend endpoints."""

import io
import time

from fastapi.testclient import TestClient

from db.database import SessionLocal, init_db
from main import app
from models.db_models import User


OWNER_HEADER = {"X-CodeLens-User": "owner"}
OTHER_HEADER = {"X-CodeLens-User": "other"}


def wait_until_ready(client: TestClient, project_id: str, headers: dict[str, str]):
    for _ in range(20):
        response = client.get(f"/upload/{project_id}/status", headers=headers)
        assert response.status_code == 200, response.text
        status = response.json()["status"]
        if status == "ready":
            return
        if status == "failed":
            raise AssertionError(f"Project parsing failed: {project_id}")
        time.sleep(0.5)
    raise AssertionError(f"Project never became ready: {project_id}")


def seed_users():
    db = SessionLocal()
    try:
        for username in ("owner", "other"):
            if not db.query(User).filter(User.username == username).first():
                db.add(User(username=username, email=f"{username}@example.test"))
        db.commit()
    finally:
        db.close()


def create_project(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/upload",
        headers=headers,
        files={
            "file": (
                "owned.py",
                io.BytesIO(b"def owned():\n    return True\n"),
                "text/x-python",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def test_project_ownership():
    init_db()
    seed_users()

    with TestClient(app) as client:
        project_id = create_project(client, OWNER_HEADER)
        wait_until_ready(client, project_id, OWNER_HEADER)

        structure = client.get(
            f"/projects/{project_id}/structure",
            headers=OWNER_HEADER,
        )
        assert structure.status_code == 200, structure.text

        explanation = client.post(
            "/explain",
            headers=OWNER_HEADER,
            json={"project_id": project_id, "file_path": "owned.py"},
        )
        assert explanation.status_code == 200, explanation.text

        docs = client.post(
            "/generate-docs",
            headers=OWNER_HEADER,
            json={"project_id": project_id, "kind": "readme"},
        )
        assert docs.status_code == 200, docs.text

        diagram = client.post(
            "/generate-diagram",
            headers=OWNER_HEADER,
            json={"project_id": project_id},
        )
        assert diagram.status_code == 200, diagram.text

        ask = client.post(
            "/ask",
            headers=OWNER_HEADER,
            json={"project_id": project_id, "question": "What does owned do?"},
        )
        assert ask.status_code == 200, ask.text

        history = client.get(
            f"/history/{project_id}",
            headers=OWNER_HEADER,
        )
        assert history.status_code == 200, history.text

        audit = client.get(
            f"/audit-logs?project_id={project_id}",
            headers=OWNER_HEADER,
        )
        assert audit.status_code == 200, audit.text

        for response in (
            client.get(f"/upload/{project_id}/status", headers=OTHER_HEADER),
            client.get(f"/projects/{project_id}/structure", headers=OTHER_HEADER),
            client.post(
                "/explain",
                headers=OTHER_HEADER,
                json={"project_id": project_id, "file_path": "owned.py"},
            ),
            client.post(
                "/generate-docs",
                headers=OTHER_HEADER,
                json={"project_id": project_id, "kind": "readme"},
            ),
            client.post(
                "/generate-diagram",
                headers=OTHER_HEADER,
                json={"project_id": project_id},
            ),
            client.post(
                "/ask",
                headers=OTHER_HEADER,
                json={"project_id": project_id, "question": "What does owned do?"},
            ),
            client.get(f"/history/{project_id}", headers=OTHER_HEADER),
            client.get(
                f"/audit-logs?project_id={project_id}",
                headers=OTHER_HEADER,
            ),
        ):
            assert response.status_code == 404, response.text

        other_history = client.get("/history", headers=OTHER_HEADER)
        assert other_history.status_code == 200, other_history.text
        assert all(
            item["project_id"] != project_id
            for item in other_history.json()["projects"]
        )

        other_project_id = create_project(client, OTHER_HEADER)
        wait_until_ready(client, other_project_id, OTHER_HEADER)
        owner_history = client.get("/history", headers=OWNER_HEADER)
        assert owner_history.status_code == 200, owner_history.text
        assert any(
            item["project_id"] == project_id
            for item in owner_history.json()["projects"]
        )
        assert all(
            item["project_id"] != other_project_id
            for item in owner_history.json()["projects"]
        )


if __name__ == "__main__":
    test_project_ownership()
    print("Project ownership tests passed.")

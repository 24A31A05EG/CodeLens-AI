"""
Smoke-test the CodeLens backend endpoints.

Run while uvicorn is serving the backend. You can override the base URL with:
    $env:CODELENS_BASE_URL = 'http://127.0.0.1:8000'
    python .\test_endpoints.py
"""

import io
import json
import os
import time
import zipfile

import httpx
from fastapi.testclient import TestClient

from main import app

BASE = os.getenv("CODELENS_BASE_URL", "http://127.0.0.1:8000")


def make_test_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "sample_project/main.py",
            '''\
import os
from utils import greet


def main():
    """Entry point."""
    name = os.getenv("USER", "World")
    print(greet(name))


if __name__ == "__main__":
    main()
''',
        )
        zf.writestr(
            "sample_project/utils.py",
            '''\
def greet(name: str) -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"


class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
''',
        )
        zf.writestr("sample_project/config.json", '{"debug": true}')
    buf.seek(0)
    return buf


def make_single_file():
    return io.BytesIO(
        b'''\
import math


def circle_area(radius):
    return math.pi * radius * radius
'''
    )


def wait_until_ready(client, project_id):
    for _ in range(20):
        response = client.get(f"/upload/{project_id}/status")
        assert response.status_code == 200, response.text
        status = response.json()["status"]
        if status == "ready":
            return status
        if status == "failed":
            raise AssertionError(f"Project parsing failed: {project_id}")
        time.sleep(0.5)
    raise AssertionError(f"Project never became ready: {project_id}")


def test_all():
    try:
        client = httpx.Client(base_url=BASE, timeout=5)
        response = client.get("/health")
        if response.status_code != 200:
            client = TestClient(app)
    except Exception:
        client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200, f"Health failed: {response.text}"
    print("OK /health")

    response = client.post(
        "/upload",
        files={"file": ("sample_project.zip", make_test_zip(), "application/zip")},
    )
    assert response.status_code == 201, f"Zip upload failed: {response.text}"
    zip_project_id = response.json()["project_id"]
    print(f"OK POST /upload zip -> {zip_project_id}")

    wait_until_ready(client, zip_project_id)
    print(f"OK GET /upload/{zip_project_id}/status -> ready")

    response = client.get(f"/projects/{zip_project_id}/structure")
    assert response.status_code == 200, f"Structure failed: {response.text}"
    structure = response.json()
    assert structure["file_count"] == 3
    assert structure["languages"]["Python"] == 2
    print("OK project structure parsed")

    response = client.post(
        "/explain",
        json={
            "project_id": zip_project_id,
            "file_path": "sample_project/main.py",
            "level": "beginner",
        },
    )
    assert response.status_code == 200, f"Explain failed: {response.text}"
    explanation = response.json()
    assert explanation["file_path"] == "sample_project/main.py"
    assert "sample_project/main.py" in explanation["explanation"]
    print("OK POST /explain single file")

    response = client.post(
        "/explain",
        json={"project_id": zip_project_id, "level": "developer"},
    )
    assert response.status_code == 200, f"Project explain failed: {response.text}"
    assert len(response.json()["explanations"]) == 3
    print("OK POST /explain project-wide")

    response = client.post(
        "/generate-docs",
        json={"project_id": zip_project_id, "kind": "readme", "force_regenerate": True},
    )
    assert response.status_code == 200, f"Docs failed: {response.text}"
    docs = response.json()
    assert "# sample_project" in docs["content"]
    print("OK POST /generate-docs readme")

    response = client.post(
        "/generate-docs",
        json={"project_id": zip_project_id, "kind": "api_docs", "force_regenerate": True},
    )
    assert response.status_code == 200, f"API docs failed: {response.text}"
    assert "API Documentation" in response.json()["content"]
    print("OK POST /generate-docs api_docs")

    response = client.post(
        "/generate-diagram",
        json={"project_id": zip_project_id, "force_regenerate": True},
    )
    assert response.status_code == 200, f"Diagram failed: {response.text}"
    diagram = response.json()["mermaid"]
    assert diagram.startswith("graph TD")
    print("OK POST /generate-diagram")

    response = client.post(
        "/ask",
        json={
            "project_id": zip_project_id,
            "question": "What does the greet function do?",
        },
    )
    assert response.status_code == 200, f"Ask failed: {response.text}"
    assert response.json()["sources"]
    print("OK POST /ask")

    response = client.get(f"/history/{zip_project_id}")
    assert response.status_code == 200, f"Project history failed: {response.text}"
    history = response.json()
    assert history["project"]["project_id"] == zip_project_id
    assert history["explanations"]
    assert history["artifacts"]
    print("OK GET /history/{project_id}")

    response = client.get("/history")
    assert response.status_code == 200, f"History list failed: {response.text}"
    assert any(item["project_id"] == zip_project_id for item in response.json()["projects"])
    print("OK GET /history")

    response = client.post(
        "/upload",
        files={"file": ("math_tools.py", make_single_file(), "text/x-python")},
    )
    assert response.status_code == 201, f"Single file upload failed: {response.text}"
    file_project_id = response.json()["project_id"]
    wait_until_ready(client, file_project_id)
    print(f"OK POST /upload single file -> {file_project_id}")

    response = client.get(f"/projects/{file_project_id}/structure")
    assert response.status_code == 200, f"Single file structure failed: {response.text}"
    assert response.json()["file_count"] == 1
    print("OK single-file project parsed")

    response = client.post("/upload", files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")})
    assert response.status_code == 400
    print("OK unsupported file type rejected")

    response = client.get("/upload/nonexistent/status")
    assert response.status_code == 404
    print("OK nonexistent project returns 404")

    response = client.post(
        "/explain",
        json={
            "project_id": zip_project_id,
            "file_path": "../../etc/passwd",
            "level": "beginner",
        },
    )
    assert response.status_code == 400
    print("OK path traversal blocked")

    response = client.post("/upload", data={"github_url": "http://evil.com/repo"})
    assert response.status_code == 400
    print("OK unsafe URL blocked")

    print("All backend endpoint tests passed.")
    print(json.dumps({"zip_project_id": zip_project_id, "file_project_id": file_project_id}))


if __name__ == "__main__":
    test_all()

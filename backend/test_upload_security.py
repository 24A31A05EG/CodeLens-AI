"""Focused tests for ZIP extraction safety limits."""

import io
import stat
import zipfile

from fastapi.testclient import TestClient

from db.database import init_db
from main import app


def make_special_file_zip():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        member = zipfile.ZipInfo("unsafe-link")
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(member, "outside-target")
    archive.seek(0)
    return archive


def test_special_zip_entries_are_rejected():
    init_db()

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={
                "file": (
                    "unsafe.zip",
                    make_special_file_zip(),
                    "application/zip",
                )
            },
        )

    assert response.status_code == 400, response.text
    assert "special-file" in response.json()["detail"]


if __name__ == "__main__":
    test_special_zip_entries_are_rejected()
    print("ZIP security tests passed.")
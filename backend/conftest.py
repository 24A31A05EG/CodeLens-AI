"""pytest defaults: use throw-away SQLite + storage unless the caller configured their own."""

import os
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(tempfile.gettempdir(), 'codelens_pytest.db')}")
os.environ.setdefault("CODELENS_STORAGE_ROOT", tempfile.mkdtemp(prefix="codelens_pytest_"))

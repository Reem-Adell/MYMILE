"""
Shared, isolated test environment. EVERY test module must import this first:

    from tests import _env  # noqa: F401  (must come before any `app.*` import)

What it guarantees, for the whole test process:
  * One temporary SQLite file shared by all test modules, whatever order they
    run in. The path is chosen here and written to MYMILE_DB_PATH
    unconditionally (a value already set in the shell is ignored).
  * A fresh random SECRET_KEY, so tests never depend on backend/.env.
  * An explicit runtime check (not `assert`, so it also runs under `python -O`)
    that raises if the database the app will use is the real users.db, or is
    not the temporary file chosen here.
"""
import os
import secrets
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REAL_DB_PATH = (BACKEND_DIR / "data" / "users.db").resolve()

# Reuse the path if this same process already set it up (e.g. the module was
# imported under two names); a marker left in the shell by another process
# does not match our PID and is ignored.
_OWNER_VAR = "MYMILE_TEST_ENV_OWNER_PID"
if os.environ.get(_OWNER_VAR) == str(os.getpid()) and os.environ.get("MYMILE_TEST_DB_PATH"):
    TEST_DB = os.environ["MYMILE_TEST_DB_PATH"]
    TMP_DIR = os.path.dirname(TEST_DB)
else:
    TMP_DIR = tempfile.mkdtemp(prefix="mymile-tests-")
    TEST_DB = os.path.join(TMP_DIR, "users.db")
    os.environ["MYMILE_TEST_DB_PATH"] = TEST_DB
    os.environ[_OWNER_VAR] = str(os.getpid())
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["MYMILE_DB_PATH"] = TEST_DB
# External APIs with credentials or contact details configured in backend/.env
# must never be called by tests. Environment variables take precedence over the
# .env file, so these empty values switch the integrations off; tests that need
# them patch `settings` explicitly and mock the HTTP layer.
os.environ["HOTEL_API_KEY"] = ""
os.environ["CHANNEL3_API_KEY"] = ""
os.environ["WIKIMEDIA_CONTACT"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["LLM_MODEL_NAME"] = ""
os.environ["LOG_LEVEL"] = "WARNING"  # keep test output quiet; logging tests set their own level


class UnsafeTestDatabaseError(RuntimeError):
    """The test run would touch a database other than its own temporary file."""


def ensure_not_real_db(path) -> None:
    """Raise if `path` resolves to the real backend/data/users.db."""
    if Path(path).resolve() == REAL_DB_PATH:
        raise UnsafeTestDatabaseError(f"Refusing to run tests against the real database: {REAL_DB_PATH}")


def ensure_isolated_db() -> None:
    """Raise unless the app's DB_PATH is exactly this run's temporary file."""
    from app.core import database  # safe: importing it does not open the DB

    db_path = Path(database.DB_PATH).resolve()
    ensure_not_real_db(db_path)
    if db_path == Path(database.DEFAULT_DB_PATH).resolve():
        raise UnsafeTestDatabaseError("Refusing to run tests against the app's default database path.")
    if db_path != Path(TEST_DB).resolve():
        raise UnsafeTestDatabaseError(
            "app.core.database was imported before tests._env, so its DB_PATH is not the "
            f"isolated test database ({database.DB_PATH} != {TEST_DB}).")


ensure_isolated_db()

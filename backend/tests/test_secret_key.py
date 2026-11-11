"""
SECRET_KEY startup validation.

Run from backend/:
    venv\\Scripts\\python -m unittest discover -s tests -v

Settings are built with `_env_file=None` so these tests never read the real
backend/.env, and the subprocess checks use a throwaway database.
"""
import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# app.core.config builds `settings` at import time, so a valid key must exist
# before the import. The shared test environment sets a fresh random
# SECRET_KEY (ignoring backend/.env and the shell) and the isolated temp DB.
from tests import _env  # noqa: E402,F401

from app.core.config import (  # noqa: E402
    KNOWN_INSECURE_SECRET_KEYS,
    InsecureSecretKeyError,
    Settings,
)

PUBLIC_DEFAULT = "mymile-hackathon-super-secret-key-change-in-production-2026"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def build(**kwargs):
    return Settings(_env_file=None, **kwargs)


class SecretKeyValidationTest(unittest.TestCase):

    def test_rejects_public_default_key(self):
        with self.assertRaises(InsecureSecretKeyError):
            build(SECRET_KEY=PUBLIC_DEFAULT)

    def test_rejects_public_default_with_case_or_whitespace_changes(self):
        for variant in (PUBLIC_DEFAULT.upper(), f"  {PUBLIC_DEFAULT}  "):
            with self.assertRaises(InsecureSecretKeyError):
                build(SECRET_KEY=variant)

    def test_rejects_missing_key(self):
        env = {k: v for k, v in os.environ.items() if k.upper() != "SECRET_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InsecureSecretKeyError):
                build()

    def test_rejects_empty_and_whitespace_key(self):
        for value in ("", "   ", "\t\n"):
            with self.assertRaises(InsecureSecretKeyError):
                build(SECRET_KEY=value)

    def test_rejects_every_known_placeholder(self):
        for value in KNOWN_INSECURE_SECRET_KEYS:
            with self.assertRaises(InsecureSecretKeyError, msg=value):
                build(SECRET_KEY=value)

    def test_rejects_short_key(self):
        with self.assertRaises(InsecureSecretKeyError):
            build(SECRET_KEY="x" * 31)

    def test_accepts_random_secret(self):
        key = secrets.token_urlsafe(48)
        self.assertEqual(build(SECRET_KEY=key).SECRET_KEY, key)

    def test_accepts_key_from_environment(self):
        key = secrets.token_urlsafe(48)
        with mock.patch.dict(os.environ, {"SECRET_KEY": key}):
            self.assertEqual(build().SECRET_KEY, key)

    def test_error_message_never_contains_the_key(self):
        leaky = "short-but-unique-value-7f3a"
        with self.assertRaises(InsecureSecretKeyError) as ctx:
            build(SECRET_KEY=leaky)
        self.assertNotIn(leaky, str(ctx.exception))
        self.assertNotIn(leaky, repr(ctx.exception))

    def test_key_hidden_from_settings_repr(self):
        key = secrets.token_urlsafe(48)
        s = build(SECRET_KEY=key)
        self.assertNotIn(key, repr(s))
        self.assertNotIn(key, str(s))


class AppStartupTest(unittest.TestCase):
    """Importing app.main is what uvicorn does at startup."""

    def _import_app(self, secret_key):
        tmp = tempfile.mkdtemp(prefix="mymile-secret-test-")
        env = dict(os.environ, MYMILE_DB_PATH=os.path.join(tmp, "users.db"),
                   PYTHONDONTWRITEBYTECODE="1")
        if secret_key is None:
            env.pop("SECRET_KEY", None)
        else:
            env["SECRET_KEY"] = secret_key
        # cwd=tmp: no backend/.env is found, so only the env var counts.
        return subprocess.run([sys.executable, "-c", "import app.main"], cwd=tmp,
                              env=dict(env, PYTHONPATH=str(BACKEND_DIR)),
                              capture_output=True, text=True, timeout=120)

    def test_app_refuses_to_start_with_public_default(self):
        out = self._import_app(PUBLIC_DEFAULT)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("InsecureSecretKeyError", out.stderr)
        self.assertNotIn(PUBLIC_DEFAULT, out.stderr)

    def test_app_refuses_to_start_without_key(self):
        out = self._import_app(None)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("InsecureSecretKeyError", out.stderr)

    def test_app_starts_with_random_secret(self):
        key = secrets.token_urlsafe(48)
        out = self._import_app(key)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertNotIn(key, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()

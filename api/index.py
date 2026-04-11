import sys
import os

# Point APP_ROOT at the project root so Flask finds templates/ and static/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('APP_ROOT', _project_root)

# SQLite goes in /tmp on Vercel (writable, but ephemeral per-invocation)
os.environ.setdefault('DB_PATH', '/tmp/fuel_prices.db')

sys.path.insert(0, _project_root)

from app import app  # noqa: E402 — must come after env setup

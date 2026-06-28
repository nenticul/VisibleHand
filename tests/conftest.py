"""
Shared test configuration.

Forces an in-memory SQLite database so the unit/integration suite runs with no
Postgres, no psycopg2, and no network — which is what makes CI fast and green.
This must run before any `api.*` module is imported, so it lives at module top
level in conftest (collected first by pytest).
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Ensure the project root is importable (api/, core/).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── SQLAlchemy pure-Python stub ───────────────────────────────────────────────
# On Windows, SQLAlchemy's Cython .pyd extensions hang on first import when
# Windows Defender is scanning the DLL. We inject pure-Python stubs into
# sys.modules *before* any api.* module is imported so no .pyd file is ever
# loaded during the test session. The actual DB layer is mocked in each test.
if "sqlalchemy" not in sys.modules:

    class _Col:
        """Stub for a SQLAlchemy column — supports comparison operators and attribute chaining
        so that expressions like `Model.field.desc()` and `Model.field >= value` work without
        loading any .pyd files."""
        def __ge__(self, o): return self
        def __le__(self, o): return self
        def __gt__(self, o): return self
        def __lt__(self, o): return self
        def __eq__(self, o): return self
        def __ne__(self, o): return self
        def __and__(self, o): return self
        def __or__(self, o): return self
        def __getattr__(self, n): return _Col()
        def __call__(self, *a, **kw): return _Col()

    def _declarative_base(**kwargs):
        def _init(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
        return type("Base", (object,), {
            "metadata": MagicMock(),
            "__abstract__": True,
            "__init__": _init,
        })

    def _sessionmaker(**kwargs):
        def _factory():
            return MagicMock()
        return _factory

    def _create_engine(url, **kwargs):
        return MagicMock()

    # sqlalchemy.orm stub
    _sqla_orm = types.ModuleType("sqlalchemy.orm")
    _sqla_orm.declarative_base = _declarative_base
    _sqla_orm.sessionmaker = _sessionmaker
    _sqla_orm.Session = type("Session", (object,), {})
    _sqla_orm.relationship = MagicMock()

    # sqlalchemy (core) stub
    _sqla = types.ModuleType("sqlalchemy")
    _sqla.Column = lambda *a, **kw: _Col()
    _sqla.Index = lambda *a, **kw: None
    _sqla.UniqueConstraint = lambda *a, **kw: None
    _sqla.create_engine = _create_engine
    _sqla.text = lambda s: s
    _sqla.func = MagicMock()
    _sqla.orm = _sqla_orm
    for _t in ("String", "Float", "Integer", "DateTime", "Text", "Boolean",
               "BigInteger", "Numeric", "Date", "LargeBinary"):
        setattr(_sqla, _t, lambda *a, **kw: None)

    sys.modules["sqlalchemy"] = _sqla
    sys.modules["sqlalchemy.orm"] = _sqla_orm
    sys.modules["sqlalchemy.orm.session"] = _sqla_orm
    sys.modules["sqlalchemy.orm.decl_api"] = _sqla_orm
    sys.modules["sqlalchemy.sql"] = MagicMock()
    sys.modules["sqlalchemy.sql.expression"] = MagicMock()
    sys.modules["sqlalchemy.exc"] = MagicMock()
    sys.modules["sqlalchemy.engine"] = MagicMock()
    sys.modules["sqlalchemy.pool"] = MagicMock()
    sys.modules["sqlalchemy.dialects"] = MagicMock()
    sys.modules["sqlalchemy.dialects.postgresql"] = MagicMock()
    sys.modules["sqlalchemy.dialects.sqlite"] = MagicMock()

# ── Environment ───────────────────────────────────────────────────────────────
# Point the app at SQLite *before* config/database are imported & cached.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("INGESTION_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "development")

# Reset the settings cache in case something imported it already.
try:
    from api.config import get_settings
    get_settings.cache_clear()
except Exception:
    pass

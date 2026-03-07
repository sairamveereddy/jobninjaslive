import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Base


def _default_sqlite_url() -> str:
    """
    Store SQLite DB outside OneDrive to avoid sync-related I/O errors.
    Falls back to current working directory if LOCALAPPDATA is unavailable.
    """
    root = os.getenv("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".jobninjas_live")
    db_dir = os.path.join(root, "jobninjas_live")
    try:
        os.makedirs(db_dir, exist_ok=True)
    except OSError:
        # Best-effort; if this fails we just use CWD
        return "sqlite+aiosqlite:///./jobninjas.db"
    path = os.path.join(db_dir, "jobninjas.db")
    # Ensure forward slashes for SQLAlchemy URI on Windows
    uri_path = path.replace("\\", "/")
    return f"sqlite+aiosqlite:///{uri_path}"


_raw_url = os.getenv("DATABASE_URL", _default_sqlite_url())
# Railway Postgres gives postgresql://; async engine needs postgresql+asyncpg://
if _raw_url.startswith("postgresql://") and "+" not in _raw_url.split("?")[0]:
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
DATABASE_URL = _raw_url
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as s:
        yield s

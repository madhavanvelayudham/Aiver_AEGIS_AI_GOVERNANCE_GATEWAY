from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

class Base(DeclarativeBase):
    pass

def get_engine():
    settings = get_settings()
    connect_args = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_async_engine(settings.DATABASE_URL, connect_args=connect_args, echo=False)

def get_session_factory(engine=None):
    if engine is None:
        engine = get_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Module-level convenience variables
engine = None
_SessionLocal_factory = None
_last_db_url = None

def _check_db_init():
    global engine, _SessionLocal_factory, _last_db_url
    settings = get_settings()
    if engine is None or _last_db_url != settings.DATABASE_URL:
        engine = get_engine()
        _SessionLocal_factory = get_session_factory(engine)
        _last_db_url = settings.DATABASE_URL

class SessionLocalProxy:
    def __call__(self, *args, **kwargs):
        _check_db_init()
        return _SessionLocal_factory(*args, **kwargs)

# Proxy object allows from ... import SessionLocal to work dynamically even when settings change
SessionLocal = SessionLocalProxy()

async def init_db():
    _check_db_init()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from chatbi.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话，异常时回滚。

    包括 ``ApiError``——它只是普通 ``Exception``，不做特殊处理：处理函数
    抛出 ``ApiError``（或任何异常）会回滚本次请求的事务。如果处理函数在
    抛出 ``ApiError`` 之前已经写入了行，且那部分写入需要在部分失败时仍然
    存活，必须在抛出之前自行 ``commit()``；否则这些写入会随事务一起丢失。
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

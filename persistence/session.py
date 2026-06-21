from contextlib import contextmanager

from sqlmodel import Session, create_engine

from config.settings import bot_settings

engine = create_engine(
    bot_settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    future=True,
)


@contextmanager
def get_session():
    """
    Genera una sesion por llamada.
    En el bot se usa directamente como context manager en el repositorio.
    Compatible con FastAPI Depends si el proyecto crece a una API.
    """
    with Session(engine) as session:
        yield session

from sqlalchemy import event
from sqlmodel import SQLModel

import persistence.base  # noqa: F401 — asegura que los modelos esten registrados
from persistence.session import engine


def create_db_and_tables() -> None:
    """
    Crea todas las tablas segun los modelos actuales.
    Llamar una vez al arrancar el bot (idempotente: usa IF NOT EXISTS).
    """
    SQLModel.metadata.create_all(bind=engine)


# Activar FK enforcement solo en SQLite
if engine.url.drivername.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

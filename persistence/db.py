"""
Persistencia simple en SQLite: guarda cada señal, orden y fill para
poder auditar el comportamiento del bot despues.

TODO: definir tablas (signals, orders, fills) y funciones save_*().
Para empezar simple, sqlite3 de la libreria estandar es suficiente;
solo migrar a Postgres si el volumen de datos lo justifica.
"""
import sqlite3
from pathlib import Path

from config.settings import bot_settings

DB_PATH = Path(bot_settings.db_path)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            signal TEXT
        )"""
    )
    # TODO: tablas orders y fills
    return conn

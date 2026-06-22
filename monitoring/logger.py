"""
Configuracion centralizada de logging.

Formato controlado por la variable de entorno LOG_FORMAT:
  text  (defecto) — legible en consola durante desarrollo local
  json            — una linea JSON por evento, para CloudWatch Logs en AWS

Uso:
    from monitoring.logger import setup_logging
    setup_logging()   # llama una sola vez al arrancar el proceso
"""
import logging

from pythonjsonlogger.json import JsonFormatter

from config.settings import bot_settings

_TEXT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_JSON_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()

    if bot_settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter(_JSON_FORMAT))
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    logging.root.setLevel(level)
    logging.root.handlers = [handler]
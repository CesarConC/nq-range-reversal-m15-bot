"""
Notificaciones para eventos criticos: conexion perdida, orden rechazada,
breach de riesgo, etc.

TODO: implementar el envio real, ej. via webhook de Discord o bot de
Telegram. Mantenlo simple: una funcion send_alert(message: str).
"""
import logging

logger = logging.getLogger(__name__)


def send_alert(message: str) -> None:
    # TODO: reemplazar por una llamada real a Telegram/Discord
    logger.critical("ALERTA: %s", message)

"""
Configuracion central del bot.

Lee credenciales y entorno desde variables de entorno (.env).
Nunca hardcodear credenciales en el codigo fuente.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from pydantic_settings import BaseSettings
from pydantic import AnyUrl, Field

load_dotenv()


@dataclass(frozen=True)
class TradovateConfig:
    environment: str  # "demo" o "live"
    username: str
    password: str
    app_id: str
    app_version: str
    cid: str
    secret: str
    device_id: str

    @property
    def rest_base_url(self) -> str:
        if self.environment == "live":
            return "https://live.tradovateapi.com/v1"
        return "https://demo.tradovateapi.com/v1"

    @property
    def user_ws_url(self) -> str:
        """Socket para datos de cuenta/ordenes/posiciones (sync de usuario)."""
        if self.environment == "live":
            return "wss://live.tradovateapi.com/v1/websocket"
        return "wss://demo.tradovateapi.com/v1/websocket"

    @property
    def md_ws_url(self) -> str:
        """Socket de market data. Es el mismo host para demo y live; lo que
        cambia es el mdAccessToken usado al autorizar la conexion."""
        return "wss://md.tradovateapi.com/v1/websocket"


def load_config() -> TradovateConfig:
    env = os.getenv("TRADOVATE_ENV", "demo").lower()

    required = ["TRADOVATE_USERNAME", "TRADOVATE_PASSWORD", "TRADOVATE_CID", "TRADOVATE_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Faltan variables de entorno: {', '.join(missing)}. "
            f"Copia .env.example como .env y rellena tus datos."
        )

    return TradovateConfig(
        environment=env,
        username=os.environ["TRADOVATE_USERNAME"],
        password=os.environ["TRADOVATE_PASSWORD"],
        app_id=os.getenv("TRADOVATE_APP_ID", "MyTradingBot"),
        app_version=os.getenv("TRADOVATE_APP_VERSION", "1.0"),
        cid=os.environ["TRADOVATE_CID"],
        secret=os.environ["TRADOVATE_SECRET"],
        device_id=os.getenv("TRADOVATE_DEVICE_ID", "bot-device-001"),
    )

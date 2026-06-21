"""
Configuracion central del bot.

Dos bloques diferenciados:

  TradovateConfig  - credenciales y URLs de conexion a Tradovate.
                     Lee variables de entorno con prefijo TRADOVATE_.

  BotSettings      - parametros de negocio y operacion del bot.
                     Lee variables de entorno con prefijo BOT_.
                     Todos tienen valores por defecto para poder arrancar
                     sin fichero .env; sobreescribelos en .env o como
                     variables de entorno en produccion/nube.

Nunca hardcodear credenciales en el codigo fuente.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


# --------------------------------------------------------------------------- #
# Conexion a Tradovate (credenciales)
# --------------------------------------------------------------------------- #

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
        """Socket de market data. Mismo host para demo y live; lo que
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


# --------------------------------------------------------------------------- #
# Parametros de negocio y operacion del bot  (prefijo BOT_ en env vars)
# --------------------------------------------------------------------------- #

class BotSettings(BaseSettings):
    # --- Contrato ---
    symbol: str = Field(default="MNQU6")          # simbolo del contrato frontal
    point_value: float = Field(default=2.0)        # USD/punto: MNQ=2.0, NQ=20.0

    # --- Cuenta fondeada ---
    initial_balance: float = Field(default=50_000.0)
    max_drawdown: float = Field(default=2_000.0)
    profit_target: float = Field(default=3_000.0)
    consistency_pct: float = Field(default=0.50)   # ningun dia puede superar este % del objetivo
    max_contracts: int = Field(default=1)
    risk_pct: float = Field(default=0.015)         # 1.5% del balance inicial por operacion

    # --- Estrategia ---
    rr_ratio: float = Field(default=0.33)          # reward = 0.33 * risk

    # --- WebSocket ---
    heartbeat_interval: float = Field(default=2.5) # segundos entre heartbeats a Tradovate

    # --- Persistencia ---
    risk_state_path: str = Field(default="risk_state.json")
    db_path: str = Field(default="bot.db")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BOT_",
        case_sensitive=False,
        extra="ignore",
    )


bot_settings = BotSettings()

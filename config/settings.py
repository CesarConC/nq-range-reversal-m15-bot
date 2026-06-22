"""
Configuracion central del bot.

Dos bloques diferenciados:

  TradovateConfig  - credenciales y URLs de conexion a Tradovate.
                     Lee variables de entorno con prefijo TRADOVATE_.

  BotSettings      - parametros de negocio y operacion del bot.
                     Cada campo declara explicitamente su variable de entorno;
                     todos tienen valor por defecto para arrancar sin .env.
                     En produccion/nube sobreescribe los que necesites.

Nunca hardcodear credenciales en el codigo fuente.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

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
# Parametros de negocio y operacion del bot
# --------------------------------------------------------------------------- #

class BotSettings(BaseSettings):
    # --- Contrato ---
    SYMBOL: str = Field(default="MNQU6", env='SYMBOL')
    POINT_VALUE: float = Field(default=2.0, env='POINT_VALUE')          # USD/punto: MNQ=2.0, NQ=20.0

    # --- Cuenta fondeada ---
    INITIAL_BALANCE: float = Field(default=50_000.0, env='INITIAL_BALANCE')
    MAX_DRAWDOWN: float = Field(default=2_000.0, env='MAX_DRAWDOWN')
    PROFIT_TARGET: float = Field(default=3_000.0, env='PROFIT_TARGET')
    CONSISTENCY_PCT: float = Field(default=0.50, env='CONSISTENCY_PCT')  # ningun dia puede superar este % del objetivo
    MAX_CONTRACTS: int = Field(default=1, env='MAX_CONTRACTS')
    RISK_PCT: float = Field(default=0.015, env='RISK_PCT')               # 1.5% del balance inicial por operacion

    # --- Estrategia ---
    RR_RATIO: float = Field(default=0.33, env='RR_RATIO')               # reward = 0.33 * risk

    # --- Logging ---
    LOG_FORMAT: str = Field(default="text", env='LOG_FORMAT')  # "text" en local, "json" en AWS

    # --- WebSocket ---
    HEARTBEAT_INTERVAL: float = Field(default=2.5, env='HEARTBEAT_INTERVAL')  # segundos entre heartbeats

    # --- Persistencia ---
    DB_PATH: str = Field(default="bot.db", env='DB_PATH')
    DATABASE_URL: str = Field(default="", env='DATABASE_URL')

    @model_validator(mode='after')
    def _resolve_database_url(self) -> 'BotSettings':
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite:///{Path(self.DB_PATH).resolve()}"
        return self

    class Config:
        env_file = '.env'
        case_sensitive = True


bot_settings = BotSettings()


# --------------------------------------------------------------------------- #
# Registro de estrategias
# --------------------------------------------------------------------------- #

class StrategyRegistry:
    """
    Mapea nombre de estrategia → ruta completa de la clase (modulo.Clase).

    Para registrar una nueva estrategia añade una entrada aqui;
    no hace falta importar nada de strategy/ en este fichero.
    """
    REGISTRY: dict[str, str] = {
        "range_reversal_m15": "strategy.my_strategy.MyStrategy",
    }

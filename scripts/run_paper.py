"""
Punto de entrada del bot. Lee la tabla 'account' de la base de datos y
arranca un engine independiente por cada cuenta activa, todos corriendo
en el mismo event loop con asyncio.gather().

Para añadir una cuenta: inserta una fila en 'account' con is_active=True.
Para desactivarla: pon is_active=False y reinicia el proceso.

Credenciales:
  - Local/dev:  variables de entorno TRADOVATE_* del .env.
  - AWS:        cada cuenta tiene un secreto en Secrets Manager referenciado
                por account.secrets_key. Implementar _load_credentials() para
                ese entorno cuando se despliegue en ECS.

Uso:
    cp .env.example .env   # rellena tus credenciales
    pip install -r requirements.txt
    python -m scripts.run_paper
"""
import asyncio
import logging
import os

from monitoring.logger import setup_logging
from config.settings import TradovateConfig
from tradovate.auth import TradovateAuth
from tradovate.rest_client import TradovateRestClient
from market_data.feed import MarketDataFeed
from account_data.user_socket import UserDataSocket
from core.engine import Engine
from strategy.registry import build_strategy
from risk.risk_manager import FundedAccountRules, RiskManager
from execution.order_manager import OrderManager
from persistence.init_db import create_db_and_tables
from persistence.models import Account
from persistence.repository import TradeRepository
from persistence.session import get_session

setup_logging()
logger = logging.getLogger("run_paper")

_RESTART_DELAY_SECONDS = 30


def _load_credentials(account: Account) -> TradovateConfig:
    """
    Carga las credenciales de Tradovate para la cuenta.

    Local/dev: lee las variables TRADOVATE_* del entorno (.env).
               El campo account.secrets_key se ignora.

    AWS:       sustituir el cuerpo por una llamada a Secrets Manager:
               import boto3
               secret = boto3.client('secretsmanager').get_secret_value(
                   SecretId=account.secrets_key)['SecretString']
               data = json.loads(secret)
               return TradovateConfig(environment=account.tradovate_env, **data)
    """
    required = ["TRADOVATE_PASSWORD", "TRADOVATE_CID", "TRADOVATE_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"[{account.account_id}] Faltan variables de entorno: {', '.join(missing)}. "
            f"Copia .env.example como .env y rellena tus credenciales."
        )
    return TradovateConfig(
        environment=account.tradovate_env,
        username=account.username,
        password=os.environ["TRADOVATE_PASSWORD"],
        app_id=os.getenv("TRADOVATE_APP_ID", "MyTradingBot"),
        app_version=os.getenv("TRADOVATE_APP_VERSION", "1.0"),
        cid=os.environ["TRADOVATE_CID"],
        secret=os.environ["TRADOVATE_SECRET"],
        device_id=os.getenv("TRADOVATE_DEVICE_ID", "bot-device-001"),
    )


async def _run_account_once(account: Account, trade_repo: TradeRepository) -> None:
    """Una iteracion completa del bot para una cuenta. Lanza excepcion si algo falla."""
    log = logging.getLogger(f"account.{account.account_id}")
    config = _load_credentials(account)

    auth = TradovateAuth(config)
    session = await auth.login()

    if not session.has_market_data:
        log.error("Sin acceso a market data. Revisa la suscripcion del API add-on en Tradovate.")
        return

    rest_client = TradovateRestClient(config, auth)
    order_manager = OrderManager(rest_client, device_id=config.device_id)
    await order_manager.initialize()

    rules = FundedAccountRules(
        initial_balance=account.initial_balance,
        max_drawdown=account.max_drawdown,
        profit_target=account.profit_target,
        consistency_pct=account.consistency_pct,
        max_contracts=account.max_contracts,
        risk_pct=account.risk_pct,
        point_value=account.point_value,
    )

    with get_session() as db:
        max_eod_balance = trade_repo.load_risk_state(
            account.account_id, rules.initial_balance, db
        )
    risk_manager = RiskManager(rules, max_eod_balance=max_eod_balance)

    strategy = build_strategy(account.strategy)
    engine = Engine(
        strategy=strategy,
        symbol=account.symbol,
        account_id=account.account_id,
        risk_manager=risk_manager,
        order_manager=order_manager,
        trade_repo=trade_repo,
        contract_multiplier=account.point_value,
    )

    feed = MarketDataFeed(
        md_ws_url=config.md_ws_url,
        md_access_token=session.md_access_token,
        on_quote=engine.on_quote,
    )
    await feed.connect()
    await feed.subscribe(account.symbol)

    user_socket = UserDataSocket(
        user_ws_url=config.user_ws_url,
        access_token=session.access_token,
        on_order_update=lambda o: log.info("Orden actualizada: %s", o),
        on_fill=engine.on_fill,
        on_position_update=lambda p: log.info("Posicion actualizada: %s", p),
    )
    await user_socket.connect()
    await user_socket.sync()

    log.info(
        "Bot corriendo en %s | simbolo=%s | trailing_limit=%.2f | max_profit_dia=%.2f",
        account.tradovate_env, account.symbol,
        risk_manager.trailing_loss_limit, risk_manager.max_daily_profit,
    )

    await asyncio.Future()  # corre indefinidamente hasta Ctrl+C o excepcion


async def run_account(account: Account, trade_repo: TradeRepository) -> None:
    """
    Mantiene el bot de una cuenta en marcha. Si falla, espera
    _RESTART_DELAY_SECONDS y vuelve a intentarlo.
    """
    log = logging.getLogger(f"account.{account.account_id}")
    while True:
        try:
            await _run_account_once(account, trade_repo)
        except asyncio.CancelledError:
            log.info("Detenido.")
            return
        except Exception:
            log.exception(
                "Error inesperado. Reintentando en %d segundos...",
                _RESTART_DELAY_SECONDS,
            )
            await asyncio.sleep(_RESTART_DELAY_SECONDS)


async def main() -> None:
    create_db_and_tables()

    trade_repo = TradeRepository()

    with get_session() as db:
        accounts = trade_repo.get_active_accounts(db)

    if not accounts:
        logger.error(
            "No hay cuentas activas en la tabla 'account'. "
            "Inserta al menos una fila con is_active=True y reinicia el bot."
        )
        return

    logger.info(
        "Arrancando %d cuenta(s): %s",
        len(accounts),
        [a.account_id for a in accounts],
    )

    await asyncio.gather(*[run_account(a, trade_repo) for a in accounts])


if __name__ == "__main__":
    asyncio.run(main())
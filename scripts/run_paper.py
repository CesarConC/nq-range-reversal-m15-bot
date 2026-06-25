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
import signal
from datetime import datetime, timedelta, timezone

from monitoring.logger import setup_logging
from config.settings import TradovateConfig, bot_settings
from tradovate.auth import TradovateAuth
from tradovate.rest_client import TradovateRestClient
from market_data.feed import MarketDataFeed
from account_data.user_socket import UserDataSocket
from core.engine import Engine
from core.reconciler import reconcile
from strategy.registry import build_strategy
from risk.risk_manager import FundedAccountRules, RiskManager
from execution.order_manager import OrderManager
from persistence.init_db import create_db_and_tables
from persistence.models import Account
from persistence.repository import TradeRepository
from persistence.session import get_session
from tradovate.models import Candle

setup_logging()
logger = logging.getLogger("run_paper")


async def _seed_m15_bar(engine: Engine, rest_client: TradovateRestClient, symbol: str) -> None:
    """Obtiene la vela M15 que esta en curso y pre-carga el aggregator del engine.

    Al arrancar el bot a mitad de un periodo M15, el aggregator desconoce los
    ticks anteriores al arranque. Este metodo recupera el OHLC acumulado desde
    el inicio real del periodo via REST y lo carga en el aggregator, de forma
    que los ticks del WebSocket continuan construyendo sobre datos completos.

    Si la API no devuelve el bar actual (red, horario fuera de mercado, etc.)
    loguea un aviso y deja el aggregator en su estado inicial: la primera vela
    M15 sera incompleta pero el bot operara con normalidad desde la siguiente.
    """
    log = logging.getLogger("seed_m15")
    try:
        now = datetime.now(timezone.utc)
        bucket_index = int(now.timestamp() / 60) // 15
        current_bucket_start = datetime.fromtimestamp(bucket_index * 15 * 60, tz=timezone.utc)

        bars = await rest_client.get_chart_bars(symbol, timeframe_minutes=15, n_bars=2)
        if not bars:
            log.warning("Sin datos historicos M15 de la API. Primera vela sera incompleta.")
            return

        matching = None
        for bar in bars:
            bar_ts = datetime.fromisoformat(bar["timestamp"].replace("Z", "+00:00"))
            if bar_ts == current_bucket_start:
                matching = bar
                break

        if matching is None:
            log.warning(
                "La API no devolvio la vela M15 actual (bucket=%s). "
                "Primera vela sera incompleta.",
                current_bucket_start.isoformat(),
            )
            return

        candle = Candle(
            timeframe="M15",
            open_time=current_bucket_start,
            close_time=current_bucket_start + timedelta(minutes=15),
            open=float(matching["open"]),
            high=float(matching["high"]),
            low=float(matching["low"]),
            close=float(matching["close"]),
        )
        engine.seed_m15_bar(candle)

    except Exception:
        log.exception(
            "Error al obtener la vela M15 actual. Primera vela sera incompleta."
        )


def _load_credentials(account: Account) -> TradovateConfig:
    """
    Carga las credenciales de Tradovate para la cuenta.

    Hay dos modos de operacion controlados por la variable USE_SECRETS_MANAGER:

      USE_SECRETS_MANAGER=false  (defecto)
        Lee TRADOVATE_PASSWORD, TRADOVATE_CID y TRADOVATE_SECRET del entorno.
        Util en local/dev con un .env. account.secrets_key se ignora.

      USE_SECRETS_MANAGER=true
        Lee las credenciales del secreto en AWS Secrets Manager referenciado
        por account.secrets_key. Las vars TRADOVATE_* del entorno se ignoran.
        El secreto debe ser un JSON con esta estructura:
          {
            "password":    "...",
            "cid":         "...",
            "secret":      "...",
            "app_id":      "MyTradingBot",   (opcional)
            "app_version": "1.0",            (opcional)
            "device_id":   "bot-device-001"  (opcional)
          }
        El campo 'username' no va en el secreto: se lee de account.username.
    """
    # ------------------------------------------------------------------ #
    # AWS Secrets Manager
    # Descomentar en produccion y asegurarse de que el Task Role de ECS
    # tiene el permiso secretsmanager:GetSecretValue sobre los secretos.
    # ------------------------------------------------------------------ #
    # if os.getenv("USE_SECRETS_MANAGER", "false").lower() == "true":
    #     import json
    #     import boto3
    #     region = os.getenv("AWS_REGION", "eu-west-1")
    #     client = boto3.client("secretsmanager", region_name=region)
    #     raw = client.get_secret_value(SecretId=account.secrets_key)["SecretString"]
    #     creds = json.loads(raw)
    #     return TradovateConfig(
    #         environment=account.tradovate_env,
    #         username=account.username,
    #         password=creds["password"],
    #         app_id=creds.get("app_id", "MyTradingBot"),
    #         app_version=creds.get("app_version", "1.0"),
    #         cid=creds["cid"],
    #         secret=creds["secret"],
    #         device_id=creds.get("device_id", "bot-device-001"),
    #     )

    # ------------------------------------------------------------------ #
    # Local / dev: variables de entorno del .env
    # ------------------------------------------------------------------ #
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
        max_eod_balance = trade_repo.load_risk_state(account.account_id, rules.initial_balance, db)
        daily_pnl      = trade_repo.get_daily_pnl(account.account_id, db)
        open_trades    = trade_repo.get_open_trades(account.account_id, db)

    open_contracts = sum(
        t["qty"] if t["direction"] == "LONG" else -t["qty"]
        for t in open_trades
    )

    if open_trades:
        log.warning(
            "Estado restaurado con posicion(es) abierta(s): open_contracts=%d, daily_pnl=%.2f — "
            "verificar en Tradovate que el estado del broker coincide con la DB.",
            open_contracts, daily_pnl,
        )
    else:
        log.info("Estado restaurado: sin posiciones abiertas, daily_pnl=%.2f", daily_pnl)

    risk_manager = RiskManager(
        rules,
        max_eod_balance=max_eod_balance,
        daily_pnl=daily_pnl,
        open_contracts=open_contracts,
    )

    await reconcile(account, rest_client, trade_repo, risk_manager)

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

    await _seed_m15_bar(engine, rest_client, account.symbol)

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

    await asyncio.Future()  # corre indefinidamente hasta cancelacion


def _log_open_positions(account: Account, trade_repo: TradeRepository, log: logging.Logger) -> None:
    """Consulta y loguea las posiciones abiertas de la cuenta al hacer shutdown."""
    try:
        with get_session() as db:
            open_trades = trade_repo.get_open_trades(account.account_id, db)
        if open_trades:
            resumen = [
                {"uid": t["uid"], "symbol": t["symbol"],
                 "direction": t["direction"], "qty": t["qty"]}
                for t in open_trades
            ]
            log.warning(
                "SHUTDOWN: %d posicion(es) abierta(s) en cuenta %s — revisar en Tradovate: %s",
                len(open_trades), account.account_id, resumen,
            )
        else:
            log.info("SHUTDOWN: sin posiciones abiertas en cuenta %s.", account.account_id)
    except Exception:
        log.exception("SHUTDOWN: no se pudo consultar posiciones abiertas de cuenta %s.", account.account_id)


async def run_account(account: Account, trade_repo: TradeRepository) -> None:
    """
    Mantiene el bot de una cuenta en marcha. Si falla, espera
    bot_settings.RESTART_DELAY_SECONDS y vuelve a intentarlo.
    Al recibir CancelledError (shutdown), loguea posiciones abiertas y termina.
    """
    log = logging.getLogger(f"account.{account.account_id}")
    while True:
        try:
            await _run_account_once(account, trade_repo)
        except asyncio.CancelledError:
            _log_open_positions(account, trade_repo, log)
            log.info("Cuenta %s detenida limpiamente.", account.account_id)
            raise  # propaga la cancelacion para que asyncio.gather termine
        except Exception:
            log.exception(
                "Error inesperado. Reintentando en %d segundos...",
                bot_settings.RESTART_DELAY_SECONDS,
            )
            await asyncio.sleep(bot_settings.RESTART_DELAY_SECONDS)


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

    gather_task = asyncio.gather(*[run_account(a, trade_repo) for a in accounts])

    loop = asyncio.get_running_loop()

    def _handle_shutdown(sig: signal.Signals) -> None:
        logger.info("Señal %s recibida. Iniciando shutdown graceful...", sig.name)
        gather_task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    try:
        await gather_task
    except asyncio.CancelledError:
        logger.info("Bot detenido correctamente.")


if __name__ == "__main__":
    asyncio.run(main())
"""
Punto de entrada del bot. Lee la tabla 'account' de la base de datos y
arranca un engine independiente por cada cuenta activa, todos corriendo
en el mismo event loop con asyncio.gather().

Para añadir una cuenta: inserta una fila en 'account' con is_active=True.
Para desactivarla: pon is_active=False y reinicia el proceso.

Uso:
    pip install -r requirements.txt
    python -m scripts.run_paper
"""
import asyncio
import logging
import signal
from datetime import datetime, timezone

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

setup_logging()
logger = logging.getLogger("run_paper")



def _load_credentials(account: Account) -> TradovateConfig:
    """Lee las credenciales de Tradovate directamente del registro de la cuenta en DB."""
    return TradovateConfig(
        environment=account.tradovate_env,
        username=account.username,
        password=account.password,
        cid=account.cid,
        secret=account.secret,
        app_id=account.app_id,
        app_version=account.app_version,
        device_id=account.device_id,
    )


async def _run_account_once(account: Account, trade_repo: TradeRepository, controller=None) -> None:
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

    strategy = build_strategy(account.strategy)

    rules = FundedAccountRules(
        initial_balance=account.initial_balance,
        max_drawdown=account.max_drawdown,
        profit_target=account.profit_target,
        consistency_pct=account.consistency_pct,
        max_contracts=account.max_contracts,
        risk_pct=strategy.risk_pct,
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

    if controller is not None:
        controller.risk_manager = risk_manager

    await reconcile(account, rest_client, trade_repo, risk_manager)
    engine = Engine(
        strategy=strategy,
        symbol=account.symbol,
        account_id=account.account_id,
        risk_manager=risk_manager,
        order_manager=order_manager,
        trade_repo=trade_repo,
        contract_multiplier=account.point_value,
    )

    if controller is not None:
        controller.engine = engine
        controller.status = "running"

    await strategy.seed_bars(engine, rest_client, account.symbol)

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
    from core.registry import controllers
    ctrl = controllers.get(account.account_id)
    log = logging.getLogger(f"account.{account.account_id}")

    while True:
        try:
            if ctrl is not None:
                ctrl.status = "connecting"
                ctrl.started_at = datetime.now(timezone.utc)
                ctrl.last_error = None
            await _run_account_once(account, trade_repo, ctrl)
        except asyncio.CancelledError:
            if ctrl is not None:
                ctrl.status = "stopped"
                ctrl.engine = None
                ctrl.risk_manager = None
            _log_open_positions(account, trade_repo, log)
            log.info("Cuenta %s detenida limpiamente.", account.account_id)
            raise  # propaga la cancelacion para que asyncio.gather termine
        except Exception:
            if ctrl is not None:
                ctrl.status = "error"
                ctrl.last_error = "Unexpected error — check logs"
                ctrl.engine = None
                ctrl.risk_manager = None
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

    # Registrar controladores antes de lanzar las tasks (run_account las lee)
    from core.registry import BotController, controllers
    from api.server import serve as serve_api

    for account in accounts:
        controllers[account.account_id] = BotController(
            account_id=account.account_id,
            account_cfg=account,
            trade_repo=trade_repo,
            run_fn=run_account,
        )

    loop = asyncio.get_running_loop()

    # Crear tasks individuales para poder pararlas/reanudarlas por cuenta
    for account in accounts:
        task = loop.create_task(
            run_account(account, trade_repo),
            name=f"bot-{account.account_id}",
        )
        controllers[account.account_id].task = task

    api_task = loop.create_task(serve_api(), name="api-server")

    def _handle_shutdown(sig: signal.Signals) -> None:
        logger.info("Señal %s recibida. Iniciando shutdown graceful...", sig.name)
        api_task.cancel()
        for ctrl in controllers.values():
            if ctrl.task and not ctrl.task.done():
                ctrl.task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    all_tasks = [controllers[a.account_id].task for a in accounts] + [api_task]
    try:
        await asyncio.gather(*all_tasks, return_exceptions=True)
    finally:
        logger.info("Bot detenido correctamente.")


if __name__ == "__main__":
    asyncio.run(main())
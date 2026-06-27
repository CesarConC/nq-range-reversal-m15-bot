"""
Punto de entrada del bot. Lee la tabla 'account' de la base de datos y
arranca un engine independiente por cada cuenta activa, todos corriendo
en el mismo event loop con asyncio.gather().

Para añadir una cuenta: inserta una fila en 'account' con is_active=True.
Para desactivarla: pon is_active=False y reinicia el proceso.

Uso:
    pip install -r requirements.txt
    python -m scripts.run_paper

Nota: la capa de conexion al broker (Rithmic) está pendiente de implementar.
Mientras tanto el proceso arranca, carga los datos de DB y expone el API del
dashboard, pero el bot permanece en estado 'stopped' sin operar.
"""
import asyncio
import logging
import signal
from datetime import datetime, timezone

from monitoring.logger import setup_logging
from config.settings import bot_settings
from core.engine import Engine
from strategy.registry import build_strategy
from risk.risk_manager import FundedAccountRules, RiskManager
from persistence.init_db import create_db_and_tables
from persistence.models import Account
from persistence.repository import TradeRepository
from persistence.session import get_session

setup_logging()
logger = logging.getLogger("run_paper")


async def _run_account_once(account: Account, trade_repo: TradeRepository, controller=None) -> None:
    """
    Stub sin conexion a broker. Carga el risk manager desde DB para que el
    dashboard pueda mostrar datos reales, luego espera hasta que se cancele.
    Se sustituira por la implementacion Rithmic cuando este lista.
    """
    log = logging.getLogger(f"account.{account.account_id}")

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

    risk_manager = RiskManager(
        rules,
        max_eod_balance=max_eod_balance,
        daily_pnl=daily_pnl,
        open_contracts=open_contracts,
    )

    engine = Engine(
        strategy=strategy,
        symbol=account.symbol,
        account_id=account.account_id,
        risk_manager=risk_manager,
        order_manager=None,
        trade_repo=trade_repo,
        contract_multiplier=account.point_value,
    )

    if controller is not None:
        controller.risk_manager = risk_manager
        controller.engine = engine
        controller.status = "running"

    log.warning(
        "Cuenta %s [%s]: sin conexion a broker — stub activo. "
        "Implementar capa Rithmic para operar en %s.",
        account.account_id, account.label, account.environment,
    )

    await asyncio.Future()  # espera hasta CancelledError (shutdown o stop via API)


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
                "SHUTDOWN: %d posicion(es) abierta(s) en cuenta %s — revisar en broker: %s",
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
            raise
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
        all_accounts = trade_repo.get_all_accounts(db)
        active_accounts = [a for a in all_accounts if a.is_active]

    logger.info(
        "%d cuenta(s) en DB — %d activa(s): %s",
        len(all_accounts),
        len(active_accounts),
        [a.account_id for a in active_accounts],
    )

    from core.registry import BotController, controllers
    from api.server import serve as serve_api

    # Registrar TODAS las cuentas como controladores para que el dashboard
    # pueda mostrarlas y controlarlas, independientemente de is_active.
    for account in all_accounts:
        controllers[account.account_id] = BotController(
            account_id=account.account_id,
            account_cfg=account,
            trade_repo=trade_repo,
            run_fn=run_account,
        )

    loop = asyncio.get_running_loop()

    # Crear tasks solo para las cuentas activas.
    bot_tasks = []
    for account in active_accounts:
        task = loop.create_task(
            run_account(account, trade_repo),
            name=f"bot-{account.account_id}",
        )
        controllers[account.account_id].task = task
        bot_tasks.append(task)

    api_task = loop.create_task(serve_api(), name="api-server")

    def _handle_shutdown(sig: signal.Signals) -> None:
        logger.info("Señal %s recibida. Iniciando shutdown graceful...", sig.name)
        api_task.cancel()
        for ctrl in controllers.values():
            if ctrl.task and not ctrl.task.done():
                ctrl.task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    all_tasks = bot_tasks + [api_task]
    try:
        await asyncio.gather(*all_tasks, return_exceptions=True)
    finally:
        logger.info("Bot detenido correctamente.")


if __name__ == "__main__":
    asyncio.run(main())
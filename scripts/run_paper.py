"""
Punto de entrada para correr el bot COMPLETO contra el entorno DEMO de
Tradovate: market data + datos de usuario + velas -> estrategia ->
riesgo -> ejecucion real (en demo).

IMPORTANTE: los limites de risk_manager de aqui abajo son PLACEHOLDERS
para poder probar el cableado end-to-end. NO reflejan todavia las reglas
reales de tu cuenta fondeada -- eso es lo siguiente que vamos a definir.
Mientras tanto, esto SI puede mandar ordenes reales (en demo) cada vez
que la estrategia genere una señal.

Uso:
    1. cp .env.example .env   y rellena tus credenciales
    2. pip install -r requirements.txt
    3. python -m scripts.run_paper
"""
import asyncio
import logging

from config.settings import load_config
from tradovate.auth import TradovateAuth
from tradovate.rest_client import TradovateRestClient
from market_data.feed import MarketDataFeed
from account_data.user_socket import UserDataSocket
from core.engine import Engine
from strategy.my_strategy import MyStrategy
from risk.risk_manager import RiskManager, RiskLimits
from execution.order_manager import OrderManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_paper")

# TODO: ajustar al contrato frontal vigente. El generico "MNQ" no funciona
# para suscripcion de market data, hace falta el simbolo especifico
# (ej. MNQU6 = Septiembre 2026). Verificalo en la plataforma de Tradovate
# o vía GET /contract/find?name=MNQ antes de correr esto.
MNQ_SYMBOL = "MNQU6"

# PLACEHOLDER -- reemplazar por las reglas reales de tu cuenta fondeada.
PLACEHOLDER_RISK_LIMITS = RiskLimits(max_daily_loss=99_999, max_contracts=1)


async def main():
    config = load_config()

    auth = TradovateAuth(config)
    session = await auth.login()

    if not session.has_market_data:
        logger.error(
            "Esta cuenta no tiene acceso a market data en vivo. "
            "Revisa tu suscripcion del API add-on en Tradovate."
        )
        return

    # --- Order manager: descubre la cuenta y queda listo para mandar ordenes ---
    rest_client = TradovateRestClient(config, auth)
    order_manager = OrderManager(rest_client, device_id=config.device_id)
    await order_manager.initialize()

    # --- Risk manager con limites PLACEHOLDER (ver advertencia arriba) ---
    risk_manager = RiskManager(PLACEHOLDER_RISK_LIMITS)

    # --- Estrategia + engine, ya con riesgo y ejecucion conectados ---
    strategy = MyStrategy()
    engine = Engine(
        strategy=strategy,
        symbol=MNQ_SYMBOL,
        risk_manager=risk_manager,
        order_manager=order_manager,
    )

    # --- Socket de market data: alimenta al engine con quotes en vivo ---
    feed = MarketDataFeed(
        md_ws_url=config.md_ws_url,
        md_access_token=session.md_access_token,
        on_quote=engine.on_quote,
    )
    await feed.connect()
    await feed.subscribe(MNQ_SYMBOL)

    # --- Socket de usuario: fills reales -> engine.on_fill -> state/riesgo ---
    user_socket = UserDataSocket(
        user_ws_url=config.user_ws_url,
        access_token=session.access_token,
        on_order_update=lambda o: logger.info("Orden actualizada: %s", o),
        on_fill=engine.on_fill,
        on_position_update=lambda p: logger.info("Posicion actualizada: %s", p),
    )
    await user_socket.connect()
    await user_socket.sync()

    logger.info(
        "Bot completo corriendo en DEMO sobre %s. Limites de riesgo son "
        "PLACEHOLDER. Ctrl+C para salir.",
        MNQ_SYMBOL,
    )
    await asyncio.Future()  # corre indefinidamente hasta Ctrl+C


if __name__ == "__main__":
    asyncio.run(main())

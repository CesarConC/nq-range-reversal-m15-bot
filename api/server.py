"""
Servidor FastAPI que corre dentro del mismo proceso que los bots.

Arranca via asyncio.create_task(serve()) en main() para que comparta
el event loop con las tasks del bot y pueda leer el registro en memoria
sin IPC ni sincronizacion adicional.
"""
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import account, bot, position, status, trades

logger = logging.getLogger(__name__)

_PREFIX = "/accounts/{account_id}"


def create_app() -> FastAPI:
    app = FastAPI(title="Bot Dashboard API", docs_url="/docs", redoc_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(status.router, prefix=_PREFIX)
    app.include_router(account.router, prefix=_PREFIX)
    app.include_router(position.router, prefix=_PREFIX)
    app.include_router(trades.router, prefix=_PREFIX)
    app.include_router(bot.router, prefix=_PREFIX)

    return app


async def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Lanza uvicorn en el event loop existente (loop='none')."""
    config = uvicorn.Config(
        app=create_app(),
        host=host,
        port=port,
        loop="none",
        log_level="warning",
    )
    server = uvicorn.Server(config)
    logger.info("API Dashboard arrancando en http://%s:%d", host, port)
    await server.serve()
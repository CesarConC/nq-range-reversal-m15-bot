"""
Punto de entrada para correr el bot completo (estrategia + riesgo +
ejecucion real) contra la cuenta LIVE fondeada.

NO usar hasta haber validado exhaustivamente con run_paper.py en demo.

TODO: una vez que strategy/, risk/, execution/ y core/engine.py esten
implementados, este script debe:
  1. cargar config con TRADOVATE_ENV=live
  2. login + listar cuentas (rest_client.list_accounts())
  3. instanciar Engine con la estrategia, risk_manager y order_manager reales
  4. conectar MarketDataFeed y el websocket de usuario
  5. dejar correr el Engine indefinidamente con manejo de reconexion
"""
import asyncio


async def main():
    raise NotImplementedError("Completar una vez validado en demo (run_paper.py)")


if __name__ == "__main__":
    asyncio.run(main())

"""
Registro global de controladores de bot, uno por cuenta activa.

Cada BotController mantiene el estado en memoria del bot de una cuenta:
status, referencia al engine/risk_manager en ejecucion, y la asyncio.Task.
La API lee y escribe sobre estas instancias para exponer estado y controlar
el ciclo de vida del bot sin tocar la base de datos en cada peticion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


@dataclass
class BotController:
    account_id: str
    account_cfg: Any        # persistence.models.Account  (evita import circular)
    trade_repo: Any         # persistence.repository.TradeRepository
    run_fn: Any = None      # async callable(account, trade_repo) -- asignado por main()
    status: Literal["running", "stopped", "connecting", "error"] = "stopped"
    engine: Optional[Any] = None        # core.engine.Engine
    risk_manager: Optional[Any] = None  # risk.risk_manager.RiskManager
    task: Optional[Any] = None          # asyncio.Task
    started_at: Optional[datetime] = None
    last_error: Optional[str] = None


# Poblado por main() antes de lanzar las tasks; leido por la API en cada request.
controllers: dict[str, BotController] = {}
"""
Capa de riesgo: valida CADA señal antes de que se convierta en una orden
real. Ninguna orden deberia salir sin pasar por aqui, sin excepcion.

TODO: completar con las reglas exactas de tu cuenta fondeada, por ejemplo:
  - perdida maxima diaria (daily loss limit)
  - drawdown maximo / trailing drawdown
  - numero maximo de contratos simultaneos
  - horario permitido de operacion
  - "consistency rule" si tu programa de fondeo la exige
"""
from dataclasses import dataclass


@dataclass
class RiskLimits:
    max_daily_loss: float
    max_contracts: int
    # TODO: agregar mas limites segun las reglas de tu fondeo


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self.daily_pnl: float = 0.0
        self.open_contracts: int = 0

    def can_open_position(self, contracts: int) -> bool:
        # TODO: chequear daily_pnl contra max_daily_loss, contracts contra max_contracts, etc.
        if self.daily_pnl <= -abs(self.limits.max_daily_loss):
            return False
        if abs(self.open_contracts) + contracts > self.limits.max_contracts:
            return False
        return True

    def register_fill(self, pnl_delta: float, contracts_delta: int) -> None:
        self.daily_pnl += pnl_delta
        self.open_contracts += contracts_delta

"""
Capa de riesgo para cuentas fondeadas con trailing drawdown EOD y
consistency rule.

REGLAS IMPLEMENTADAS (confirmadas con el usuario):

1. TRAILING DRAWDOWN EOD:
   - max_eod_balance arranca en el balance inicial ($50,000).
   - trailing_loss_limit = max_eod_balance - max_drawdown ($2,000).
   - Al final de cada dia: si el balance de cierre > max_eod_balance,
     se actualiza max_eod_balance y el limite sube. Si es <= no cambia.
   - Si el balance cae por debajo de trailing_loss_limit -> violacion.
   - Consecuencia intraday: el margen disponible para perder es
     current_balance - trailing_loss_limit. El bot no abre posicion si
     arriesga mas de eso.
   - La cuenta arranca en $50,000, el objetivo es llegar a $53,000
     ($3,000 de beneficio). El limite inicial = $50,000 - $2,000 = $48,000.

2. CONSISTENCY RULE (50%):
   - Ningun dia puede cerrar con beneficio mayor que el 50% del objetivo
     de beneficio total ($3,000 * 50% = $1,500).
   - El bot deja de operar cuando el P&L del dia se acerca a ese techo.

3. CALCULO DE CONTRATOS (dinamico por operacion):
   - Presupuesto de riesgo = initial_balance * risk_pct + max(0, daily_pnl).
     Si el dia va en negativo o a cero, solo se arriesga el % fijo de la
     cuenta. Si el dia va en positivo, se puede arriesgar ese % mas las
     ganancias acumuladas del dia.
   - Contratos = floor(presupuesto / (distancia_sl_en_puntos * point_value))
   - Resultado acotado a [0, max_contracts]. Si el resultado es 0 (SL
     demasiado lejos para el presupuesto), el motor descarta la operacion.

4. MAX CONTRATOS:
   - El bot no abre posicion si abs(contratos_abiertos) + nuevos > max.

PERSISTENCIA:
   max_eod_balance se carga desde la base de datos al arrancar el bot via
   TradeRepository.load_risk_state() y se guarda via save_risk_state()
   tras cada llamada a end_of_day(). RiskManager no gestiona persistencia.
"""
import logging
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FundedAccountRules:
    initial_balance: float       # 50_000 (balance de arranque de la cuenta)
    max_drawdown: float          # 2_000 (trailing EOD)
    profit_target: float         # 3_000 (objetivo: llegar a 53_000)
    consistency_pct: float       # 0.50 (ningun dia puede ser >50% del objetivo)
    max_contracts: int           # limite duro de contratos simultaneos
    risk_pct: float              # 0.015 (1.5% del balance inicial por operacion)
    point_value: float           # USD por punto del contrato (MNQ=2.0, NQ=20.0)

    @property
    def max_daily_profit(self) -> float:
        return self.profit_target * self.consistency_pct


class RiskManager:
    def __init__(
        self,
        rules: FundedAccountRules,
        max_eod_balance: Optional[float] = None,
    ):
        self.rules = rules

        # Estado persistente: cargado desde DB al arrancar, guardado tras end_of_day()
        self.max_eod_balance: float = (
            max_eod_balance if max_eod_balance is not None else rules.initial_balance
        )

        # Estado intraday (se resetea cada dia)
        self.daily_pnl: float = 0.0
        self.open_contracts: int = 0

        logger.info(
            "RiskManager inicializado: max_eod_balance=%.2f trailing_loss_limit=%.2f",
            self.max_eod_balance, self.trailing_loss_limit,
        )

    # ------------------------------------------------------------------ #
    # Propiedad calculada: el limite de perdida actual
    # ------------------------------------------------------------------ #
    @property
    def trailing_loss_limit(self) -> float:
        return self.max_eod_balance - self.rules.max_drawdown

    @property
    def max_daily_profit(self) -> float:
        return self.rules.max_daily_profit

    # ------------------------------------------------------------------ #
    # Calculo dinamico de contratos por operacion
    # ------------------------------------------------------------------ #
    def calculate_contracts(self, entry_price: float, stop_loss: float) -> int:
        """Devuelve el numero de contratos a operar segun el presupuesto de
        riesgo actual y la distancia al SL.

        - Si daily_pnl <= 0: presupuesto = initial_balance * risk_pct
        - Si daily_pnl > 0:  presupuesto = initial_balance * risk_pct + daily_pnl
        - Resultado acotado a [0, max_contracts]. 0 significa que el SL esta
          demasiado lejos para el presupuesto; el motor debe descartar la trade.
        """
        risk_budget = (
            self.rules.initial_balance * self.rules.risk_pct
            + max(0.0, self.daily_pnl)
        )
        sl_distance = abs(entry_price - stop_loss)
        risk_per_contract = sl_distance * self.rules.point_value
        contracts = int(risk_budget / risk_per_contract)
        contracts = min(contracts, self.rules.max_contracts)
        logger.info(
            "calculate_contracts: presupuesto=%.2f sl_dist=%.4f rpc=%.2f -> %d contratos",
            risk_budget, sl_distance, risk_per_contract, contracts,
        )
        return contracts

    # ------------------------------------------------------------------ #
    # Validacion antes de cada orden
    # ------------------------------------------------------------------ #
    def can_open_position(
        self,
        contracts: int,
        direction: Literal["LONG", "SHORT"],
        current_balance: Optional[float] = None,
    ) -> tuple[bool, str]:
        """Devuelve (allowed, reason). Si allowed es False, reason explica
        por que se bloqueo.

        direction: direccion de la nueva operacion ("LONG" o "SHORT").
        current_balance: balance real de la cuenta en este momento (si se
          conoce); si no se pasa, se usa el P&L del dia como aproximacion.
        """

        # 1. Conflicto de direccion: no se puede abrir en sentido contrario
        #    a una operacion ya abierta.
        if self.open_contracts > 0 and direction == "SHORT":
            return False, (
                f"Hay una operacion LONG abierta ({self.open_contracts} contratos). "
                f"Espera a que se cierre antes de abrir SHORT."
            )
        if self.open_contracts < 0 and direction == "LONG":
            return False, (
                f"Hay una operacion SHORT abierta ({abs(self.open_contracts)} contratos). "
                f"Espera a que se cierre antes de abrir LONG."
            )

        # 2. Consistency rule: techo de beneficio del dia
        if self.daily_pnl >= self.max_daily_profit:
            return False, (
                f"Consistency rule: P&L del dia ({self.daily_pnl:.2f}) ya alcanzo "
                f"el maximo permitido ({self.max_daily_profit:.2f})"
            )

        # 3. Trailing drawdown: margen disponible
        if current_balance is not None:
            margin = current_balance - self.trailing_loss_limit
            if margin <= 0:
                return False, (
                    f"Trailing drawdown: balance actual ({current_balance:.2f}) "
                    f"ya en o por debajo del limite ({self.trailing_loss_limit:.2f})"
                )
        else:
            if self.daily_pnl <= -(self.rules.max_drawdown):
                return False, (
                    f"P&L del dia ({self.daily_pnl:.2f}) supera el drawdown "
                    f"maximo ({self.rules.max_drawdown:.2f})"
                )

        # 4. Max contratos
        if abs(self.open_contracts) + contracts > self.rules.max_contracts:
            return False, (
                f"Max contratos: {abs(self.open_contracts)} abiertos + "
                f"{contracts} nuevos > limite de {self.rules.max_contracts}"
            )

        return True, "OK"

    # ------------------------------------------------------------------ #
    # Actualizar estado tras cada fill
    # ------------------------------------------------------------------ #
    def register_fill(self, pnl_delta: float, contracts_delta: int) -> None:
        self.daily_pnl += pnl_delta
        self.open_contracts += contracts_delta

    # ------------------------------------------------------------------ #
    # EOD: actualizar trailing drawdown y resetear contadores del dia
    # ------------------------------------------------------------------ #
    def end_of_day(self, eod_balance: float) -> None:
        """Llamar al final de cada dia de trading (o al arrancar el bot al
        dia siguiente). Si el balance de cierre es mayor que el maximo
        historico, sube el limite de perdida.

        Tras llamar a este metodo, persistir el nuevo estado via:
            trade_repo.save_risk_state(account_id, self.max_eod_balance, db)
        """
        if eod_balance > self.max_eod_balance:
            old_limit = self.trailing_loss_limit
            self.max_eod_balance = eod_balance
            logger.info(
                "EOD: max_eod_balance actualizado a %.2f. "
                "Trailing loss limit subio de %.2f a %.2f",
                eod_balance, old_limit, self.trailing_loss_limit,
            )
        else:
            logger.info(
                "EOD: balance (%.2f) no supero el maximo historico (%.2f). "
                "Trailing loss limit se mantiene en %.2f",
                eod_balance, self.max_eod_balance, self.trailing_loss_limit,
            )

        self.daily_pnl = 0.0

    def reset_daily(self) -> None:
        """Resetea los contadores intraday sin actualizar el trailing. Util
        si el bot se reinicia a mitad de dia y no se quiere contar dos veces
        el P&L de la sesion anterior."""
        self.daily_pnl = 0.0
        self.open_contracts = 0

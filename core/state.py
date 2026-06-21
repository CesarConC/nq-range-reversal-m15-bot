"""
Estado de cuenta en memoria: posicion neta, precio medio de entrada,
P&L realizado del dia y operaciones abiertas. Se actualiza con cada fill
real (via account_data/user_socket.py -> core/engine.py).

NOTA: este es un modelo simplificado de contabilidad de posicion (no
considera comisiones, ni overnight, ni splits de fills parciales mas
alla de lo basico). Sirve para que risk_manager tenga numeros con los
que trabajar; si vas a operar en serio, vale la pena cruzarlo contra el
P&L que reporta Tradovate directamente al menos al principio.
"""
from dataclasses import dataclass, field


@dataclass
class AccountState:
    position_qty: int = 0
    avg_entry_price: float = 0.0
    daily_realized_pnl: float = 0.0
    # Clave: trade_id (entero autoincremental).
    # Valor: {"direction": "LONG"/"SHORT", "entry_price": float, "qty": int}
    open_orders: dict = field(default_factory=dict)
    _next_trade_id: int = field(default=0, init=False, repr=False, compare=False)

    def reset_daily(self) -> None:
        """Resetea los contadores diarios. Llamar junto a RiskManager.reset_daily()
        o end_of_day() para mantener ambos modulos sincronizados.

        No se tocan position_qty ni avg_entry_price: reflejan la posicion real
        del broker y deben seguir siendo correctos aunque haya una posicion
        abierta overnight."""
        self.daily_realized_pnl = 0.0
        self.open_orders = {}

    def apply_fill(self, action: str, qty: int, price: float, multiplier: float) -> None:
        """
        action: "Buy" o "Sell", tal como viene en el fill de Tradovate.
        multiplier: valor en USD por punto del contrato (bot_settings.point_value).

        Tres casos posibles:
          1. Sin posicion abierta -> apertura directa.
          2. Fill en la misma direccion que la posicion -> se suma y recalcula el precio medio.
          3. Fill en contra -> cierre parcial, total o reversion. Solo el tramo
             de cierre genera P&L realizado; el tramo restante (si revierte)
             abre posicion nueva al precio del fill.

        open_orders se mantiene sincronizado con position_qty en los tres casos.
        """
        signed_qty = qty if action == "Buy" else -qty

        # --- Caso 1: plano, apertura de nueva posicion ---
        if self.position_qty == 0:
            self.position_qty = signed_qty
            self.avg_entry_price = price
            self._open_trade(signed_qty, price)
            return

        # --- Caso 2: misma direccion, se añade a la posicion existente ---
        if (self.position_qty > 0) == (signed_qty > 0):
            total_qty = self.position_qty + signed_qty
            self.avg_entry_price = (
                self.avg_entry_price * abs(self.position_qty) + price * abs(signed_qty)
            ) / abs(total_qty)
            self.position_qty = total_qty
            self._add_to_trade(abs(signed_qty))
            return

        # --- Caso 3: fill en contra, cierre parcial / total / reversion ---
        closing_qty = min(abs(signed_qty), abs(self.position_qty))
        direction = 1 if self.position_qty > 0 else -1
        pnl = direction * (price - self.avg_entry_price) * closing_qty * multiplier
        self.daily_realized_pnl += pnl

        new_position = self.position_qty + signed_qty
        self.position_qty = new_position

        if new_position == 0:
            self.avg_entry_price = 0.0
            self.open_orders.clear()
        elif abs(signed_qty) > closing_qty:
            # reversion: la parte que excede la posicion actual abre en la direccion contraria
            self.avg_entry_price = price
            self.open_orders.clear()
            self._open_trade(new_position, price)
        else:
            # cierre parcial: el precio medio de los contratos restantes no cambia
            self._reduce_trade(closing_qty)

    # ------------------------------------------------------------------ #
    # Helpers internos para mantener open_orders
    # ------------------------------------------------------------------ #

    def _open_trade(self, signed_qty: int, price: float) -> None:
        self._next_trade_id += 1
        self.open_orders[self._next_trade_id] = {
            "direction": "LONG" if signed_qty > 0 else "SHORT",
            "entry_price": price,
            "qty": abs(signed_qty),
        }

    def _add_to_trade(self, qty: int) -> None:
        """Incrementa el qty de la operacion activa (con max_contracts=1
        siempre hay a lo sumo una entrada en open_orders)."""
        if not self.open_orders:
            return
        trade_id = next(iter(self.open_orders))
        self.open_orders[trade_id]["qty"] += qty

    def _reduce_trade(self, qty: int) -> None:
        """Reduce el qty de la operacion activa tras un cierre parcial."""
        if not self.open_orders:
            return
        trade_id = next(iter(self.open_orders))
        self.open_orders[trade_id]["qty"] -= qty
        if self.open_orders[trade_id]["qty"] <= 0:
            del self.open_orders[trade_id]

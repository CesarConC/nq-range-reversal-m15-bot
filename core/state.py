"""
Estado de cuenta en memoria: posicion neta, precio medio de entrada y
P&L realizado del dia. Se actualiza con cada fill real (via
account_data/user_socket.py -> core/engine.py).

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
    open_orders: dict = field(default_factory=dict)

    def apply_fill(self, action: str, qty: int, price: float, multiplier: float = 2.0) -> None:
        """
        action: "Buy" o "Sell", tal como viene en el fill de Tradovate.
        multiplier: valor en USD por punto del contrato (MNQ = 2.0 USD/punto).

        Si el fill va en la misma direccion que la posicion actual (o no
        hay posicion), simplemente la aumenta y recalcula el precio medio.
        Si va en contra, cierra/reduce posicion y calcula el P&L realizado
        de la parte cerrada; si el tamaño del fill supera la posicion
        abierta, el resto abre posicion nueva en la direccion contraria.
        """
        signed_qty = qty if action == "Buy" else -qty

        same_direction = self.position_qty == 0 or (self.position_qty > 0) == (signed_qty > 0)

        if same_direction:
            total_qty = self.position_qty + signed_qty
            if total_qty != 0:
                self.avg_entry_price = (
                    self.avg_entry_price * abs(self.position_qty) + price * abs(signed_qty)
                ) / abs(total_qty)
            self.position_qty = total_qty
            return

        # el fill va en contra de la posicion actual -> hay cierre parcial/total
        closing_qty = min(abs(signed_qty), abs(self.position_qty))
        direction = 1 if self.position_qty > 0 else -1
        pnl = direction * (price - self.avg_entry_price) * closing_qty * multiplier
        self.daily_realized_pnl += pnl

        new_position = self.position_qty + signed_qty
        if abs(signed_qty) > abs(self.position_qty):
            # el fill no solo cierra, tambien revierte la posicion
            self.position_qty = new_position
            self.avg_entry_price = price
        else:
            self.position_qty = new_position
            # si no se revierte del todo, el precio medio de lo que queda no cambia

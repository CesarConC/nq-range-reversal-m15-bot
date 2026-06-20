"""
Carga datos historicos de MNQ desde CSV y los convierte en objetos Quote
para alimentar al backtester.

TODO: implementar load_from_csv(). Si no tienes historico propio, se puede
pedir via REST a Tradovate con /md/getchart (requiere suscripcion de
market data) o usar un proveedor externo de datos historicos de futuros.
"""
from tradovate.models import Quote


def load_from_csv(path: str) -> list[Quote]:
    raise NotImplementedError

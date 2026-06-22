"""
Carga la estrategia cuyo nombre este registrado en StrategyRegistry (config/settings.py).

Para añadir una nueva estrategia:
  1. Crea strategy/mi_nueva_estrategia.py implementando BaseStrategy.
  2. Añade una entrada en StrategyRegistry.REGISTRY en config/settings.py.
  3. Inserta una cuenta en la tabla 'account' con strategy='mi_clave'.
"""
import importlib

from strategy.base_strategy import BaseStrategy
from config.settings import StrategyRegistry


def build_strategy(name: str) -> BaseStrategy:
    """Instancia la estrategia registrada bajo 'name'."""
    module_path = StrategyRegistry.REGISTRY.get(name)
    if module_path is None:
        available = ", ".join(sorted(StrategyRegistry.REGISTRY))
        raise ValueError(
            f"Estrategia '{name}' no encontrada en el registro. "
            f"Disponibles: {available}"
        )
    module_name, class_name = module_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls()


def available_strategies() -> list[str]:
    """Devuelve los nombres de estrategia registrados, ordenados alfabeticamente."""
    return sorted(StrategyRegistry.REGISTRY)

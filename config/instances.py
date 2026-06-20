"""
Instancias compartidas y listas para usar en cualquier script del bot.

Este fichero es la capa de composicion: toma los valores de BotSettings
y construye los objetos de negocio inmutables que todos los puntos de
entrada (run_paper, run_live, run_backtest) necesitan.

Objetos con estado de ejecucion (RiskManager, Engine, etc.) NO van aqui
porque cada script debe crear su propia instancia al arrancar.
"""
from config.settings import bot_settings
from risk.risk_manager import FundedAccountRules

funded_account_rules = FundedAccountRules(
    initial_balance=bot_settings.initial_balance,
    max_drawdown=bot_settings.max_drawdown,
    profit_target=bot_settings.profit_target,
    consistency_pct=bot_settings.consistency_pct,
    max_contracts=bot_settings.max_contracts,
    risk_pct=bot_settings.risk_pct,
    point_value=bot_settings.point_value,
)

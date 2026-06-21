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
    initial_balance=bot_settings.INITIAL_BALANCE,
    max_drawdown=bot_settings.MAX_DRAWDOWN,
    profit_target=bot_settings.PROFIT_TARGET,
    consistency_pct=bot_settings.CONSISTENCY_PCT,
    max_contracts=bot_settings.MAX_CONTRACTS,
    risk_pct=bot_settings.RISK_PCT,
    point_value=bot_settings.POINT_VALUE,
)

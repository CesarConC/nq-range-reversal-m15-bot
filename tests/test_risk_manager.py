import json
import tempfile
from pathlib import Path

from risk.risk_manager import RiskManager, FundedAccountRules


RULES = FundedAccountRules(
    initial_balance=50_000,
    max_drawdown=2_000,
    profit_target=3_000,
    consistency_pct=0.50,
    max_contracts=1,
)


def rm(state_path=None):
    """Crea un RiskManager sin persistencia (para no dejar archivos)."""
    if state_path is None:
        state_path = Path(tempfile.mktemp(suffix=".json"))
    return RiskManager(RULES, state_path=state_path)


# ------------------------------------------------------------------ #
# Trailing drawdown EOD
# ------------------------------------------------------------------ #
def test_trailing_loss_limit_arranca_en_balance_menos_drawdown():
    r = rm()
    assert r.trailing_loss_limit == 50_000 - 2_000  # 48_000


def test_eod_sube_limite_si_balance_mayor():
    r = rm()
    r.end_of_day(51_000)
    assert r.max_eod_balance == 51_000
    assert r.trailing_loss_limit == 51_000 - 2_000  # 49_000


def test_eod_no_cambia_limite_si_balance_menor_o_igual():
    r = rm()
    r.end_of_day(51_000)  # sube a 51k
    r.end_of_day(50_500)  # baja, no cambia
    assert r.max_eod_balance == 51_000
    assert r.trailing_loss_limit == 49_000


def test_ejemplo_usuario_trailing_completo():
    """Replica exactamente el ejemplo del usuario:
    - Cuenta arranca en $50,000, limite en $48,000
    - Dia 1: cierro en $51,000 -> limite sube a $49,000
    - Dia 2: cierro en $50,500 (< $51,000) -> limite se mantiene en $49,000
    - Dia 3: margen disponible = $50,500 - $49,000 = $1,500"""
    r = rm()
    assert r.trailing_loss_limit == 48_000

    r.end_of_day(51_000)
    assert r.trailing_loss_limit == 49_000

    r.end_of_day(50_500)
    assert r.trailing_loss_limit == 49_000  # no bajo

    margin = 50_500 - r.trailing_loss_limit
    assert margin == 1_500


def test_dia_negativo_no_mueve_limite():
    """Si cierro un dia en negativo, el limite no se mueve y al dia
    siguiente tengo menos de $2,000 de margen."""
    r = rm()
    r.end_of_day(51_000)  # gane -> limite sube a 49k
    r.end_of_day(50_200)  # perdi -> limite se queda en 49k
    assert r.trailing_loss_limit == 49_000
    assert 50_200 - r.trailing_loss_limit == 1_200  # solo $1,200 de margen


def test_bloquea_si_pnl_negativo_supera_drawdown():
    r = rm()
    r.daily_pnl = -2_100
    allowed, reason = r.can_open_position(1)
    assert not allowed
    assert "P&L" in reason or "drawdown" in reason.lower()


def test_bloquea_con_balance_real_bajo_limite():
    r = rm()
    allowed, reason = r.can_open_position(1, current_balance=47_500)
    assert not allowed
    assert "trailing" in reason.lower()


# ------------------------------------------------------------------ #
# Consistency rule (50%)
# ------------------------------------------------------------------ #
def test_max_daily_profit():
    assert RULES.max_daily_profit == 1_500


def test_bloquea_si_pnl_positivo_alcanza_techo():
    r = rm()
    r.daily_pnl = 1_500
    allowed, reason = r.can_open_position(1)
    assert not allowed
    assert "consistency" in reason.lower()


def test_permite_si_pnl_positivo_debajo_del_techo():
    r = rm()
    r.daily_pnl = 1_400
    allowed, _ = r.can_open_position(1)
    assert allowed


# ------------------------------------------------------------------ #
# Max contratos
# ------------------------------------------------------------------ #
def test_bloquea_si_max_contratos_alcanzado():
    r = rm()
    r.open_contracts = 1
    allowed, reason = r.can_open_position(1)
    assert not allowed
    assert "contrato" in reason.lower()


def test_bloquea_si_short_ya_abierto():
    r = rm()
    r.open_contracts = -1  # short 1 contrato
    allowed, reason = r.can_open_position(1)
    assert not allowed


def test_permite_si_sin_contratos_abiertos():
    r = rm()
    allowed, _ = r.can_open_position(1)
    assert allowed


# ------------------------------------------------------------------ #
# Persistencia del estado
# ------------------------------------------------------------------ #
def test_estado_persiste_entre_sesiones():
    path = Path(tempfile.mktemp(suffix=".json"))
    try:
        r1 = RiskManager(RULES, state_path=path)
        r1.end_of_day(52_000)  # max_eod sube a 52k

        r2 = RiskManager(RULES, state_path=path)  # nueva sesion
        assert r2.max_eod_balance == 52_000
        assert r2.trailing_loss_limit == 50_000
    finally:
        path.unlink(missing_ok=True)


# ------------------------------------------------------------------ #
# Reset diario
# ------------------------------------------------------------------ #
def test_end_of_day_resetea_pnl_diario():
    r = rm()
    r.daily_pnl = 800
    r.end_of_day(50_800)
    assert r.daily_pnl == 0.0


def test_register_fill_acumula_pnl_y_contratos():
    r = rm()
    r.register_fill(pnl_delta=200, contracts_delta=1)
    assert r.daily_pnl == 200
    assert r.open_contracts == 1
    r.register_fill(pnl_delta=-50, contracts_delta=-1)
    assert r.daily_pnl == 150
    assert r.open_contracts == 0

from risk.risk_manager import RiskManager, RiskLimits


def test_blocks_when_daily_loss_exceeded():
    rm = RiskManager(RiskLimits(max_daily_loss=500, max_contracts=2))
    rm.daily_pnl = -600
    assert rm.can_open_position(1) is False


def test_allows_within_limits():
    rm = RiskManager(RiskLimits(max_daily_loss=500, max_contracts=2))
    assert rm.can_open_position(1) is True


def test_bug2_short_position_counts_against_max_contracts():
    """Bug encontrado en revision: si open_contracts = -1 (short 1 contrato),
    el check con signo daba -1 + 1 > max(1) = False, permitiendo abrir
    otra posicion. Con el fix (abs), da 1 + 1 > 1 = True, bloqueado."""
    rm = RiskManager(RiskLimits(max_daily_loss=99999, max_contracts=1))
    rm.open_contracts = -1  # ya tenemos 1 contrato short abierto
    assert rm.can_open_position(1) is False

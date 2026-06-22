"""Tests para TradeRepository (SQLModel/SQLite)."""
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

import persistence.base  # noqa: F401 — registra Signal, Trade, RiskState y Account en metadata
from persistence.common import TradeStatus
from persistence.models import Account, Signal, Trade
from persistence.repository import TradeRepository
from tradovate.models import TradeSignal

ACCOUNT = "test_account"


@pytest.fixture
def db(tmp_path):
    """Sesion sobre una DB temporal. Se pasa a cada metodo del repo."""
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def repo():
    return TradeRepository()


def _signal(direction="LONG"):
    return TradeSignal(
        direction=direction,
        entry_price=21_000.0,
        take_profit=21_100.0,
        stop_loss=20_950.0,
        reason="test",
    )


def _ts():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ #
# Señales
# ------------------------------------------------------------------ #

def test_save_signal_devuelve_uid(repo, db):
    uid = repo.save_signal("MNQU6", _signal(), _ts(), db)
    assert isinstance(uid, str)
    assert len(uid) == 36  # formato UUID4


def test_save_signal_persiste_campos(repo, db):
    uid = repo.save_signal("MNQU6", _signal("SHORT"), _ts(), db)
    row = db.get(Signal, uid)
    assert row.symbol == "MNQU6"
    assert row.direction == "SHORT"
    assert row.entry_price == 21_000.0
    assert row.executed is False


def test_mark_signal_executed(repo, db):
    uid = repo.save_signal("MNQU6", _signal(), _ts(), db)
    repo.mark_signal_executed(uid, db)
    db.refresh(db.get(Signal, uid))
    assert db.get(Signal, uid).executed is True


def test_save_signal_uids_unicos(repo, db):
    uid1 = repo.save_signal("MNQU6", _signal(), _ts(), db)
    uid2 = repo.save_signal("MNQU6", _signal(), _ts(), db)
    assert uid1 != uid2


# ------------------------------------------------------------------ #
# Trades
# ------------------------------------------------------------------ #

def test_open_trade_devuelve_uid(repo, db):
    uid = repo.open_trade(
        account_id=ACCOUNT, symbol="MNQU6", direction="LONG", qty=1,
        entry_price=21_000.0, db=db, tp=21_100.0, sl=20_950.0,
    )
    assert isinstance(uid, str)
    assert len(uid) == 36


def test_open_trade_persiste_campos(repo, db):
    uid = repo.open_trade(
        account_id=ACCOUNT, symbol="MNQU6", direction="LONG", qty=2,
        entry_price=21_000.0, db=db, tp=21_100.0, sl=20_950.0,
    )
    row = db.get(Trade, uid)
    assert row.account_id == ACCOUNT
    assert row.symbol == "MNQU6"
    assert row.direction == "LONG"
    assert row.qty == 2
    assert row.entry_price == 21_000.0
    assert row.status == TradeStatus.OPEN


def test_close_trade_actualiza_fila(repo, db):
    uid = repo.open_trade(
        account_id=ACCOUNT, symbol="MNQU6", direction="LONG", qty=1,
        entry_price=21_000.0, db=db,
    )
    repo.close_trade(trade_uid=uid, exit_price=21_080.0, db=db, pnl=160.0, exit_reason="TP")
    db.refresh(db.get(Trade, uid))
    row = db.get(Trade, uid)
    assert row.exit_price == 21_080.0
    assert row.pnl == 160.0
    assert row.exit_reason == "TP"
    assert row.status == TradeStatus.CLOSED


def test_close_trade_sin_razon(repo, db):
    uid = repo.open_trade(
        account_id=ACCOUNT, symbol="MNQU6", direction="SHORT", qty=1,
        entry_price=21_000.0, db=db,
    )
    repo.close_trade(trade_uid=uid, exit_price=20_900.0, db=db, pnl=200.0)
    db.refresh(db.get(Trade, uid))
    row = db.get(Trade, uid)
    assert row.exit_reason is None
    assert row.status == TradeStatus.CLOSED


def test_close_trade_uid_inexistente_no_explota(repo, db):
    repo.close_trade(trade_uid="00000000-0000-0000-0000-000000000000", exit_price=21_000.0, db=db, pnl=0.0)


# ------------------------------------------------------------------ #
# Enlace señal -> trade
# ------------------------------------------------------------------ #

def test_trade_enlazado_a_signal(repo, db):
    signal_uid = repo.save_signal("MNQU6", _signal(), _ts(), db)
    trade_uid = repo.open_trade(
        account_id=ACCOUNT, symbol="MNQU6", direction="LONG", qty=1,
        entry_price=21_000.0, db=db, signal_uid=signal_uid,
    )
    row = db.get(Trade, trade_uid)
    assert row.signal_uid == signal_uid


# ------------------------------------------------------------------ #
# Consultas filtradas por account_id
# ------------------------------------------------------------------ #

def test_get_open_trades_devuelve_solo_abiertas(repo, db):
    t1 = repo.open_trade(ACCOUNT, "MNQU6", "LONG", 1, 21_000.0, db)
    t2 = repo.open_trade(ACCOUNT, "MNQU6", "SHORT", 1, 21_200.0, db)
    repo.close_trade(t1, 21_100.0, db, pnl=200.0)

    abiertas = repo.get_open_trades(ACCOUNT, db)
    assert len(abiertas) == 1
    assert abiertas[0]["uid"] == t2


def test_get_open_trades_vacio(repo, db):
    assert repo.get_open_trades(ACCOUNT, db) == []


def test_get_open_trades_aisladas_por_cuenta(repo, db):
    """Trades de otra cuenta no aparecen en los resultados."""
    repo.open_trade(ACCOUNT, "MNQU6", "LONG", 1, 21_000.0, db)
    repo.open_trade("otra_cuenta", "MNQU6", "LONG", 1, 21_000.0, db)
    assert len(repo.get_open_trades(ACCOUNT, db)) == 1


def test_get_trades_devuelve_todas(repo, db):
    repo.open_trade(ACCOUNT, "MNQU6", "LONG", 1, 21_000.0, db)
    repo.open_trade(ACCOUNT, "MNQU6", "LONG", 1, 21_100.0, db)
    assert len(repo.get_trades(ACCOUNT, db)) == 2


def test_get_trades_filtro_symbol(repo, db):
    repo.open_trade(ACCOUNT, "MNQU6", "LONG", 1, 21_000.0, db)
    repo.open_trade(ACCOUNT, "NQU6", "LONG", 1, 21_000.0, db)
    trades = repo.get_trades(ACCOUNT, db, symbol="MNQU6")
    assert len(trades) == 1
    assert trades[0]["symbol"] == "MNQU6"


# ------------------------------------------------------------------ #
# Estado de riesgo
# ------------------------------------------------------------------ #

def test_load_risk_state_sin_registro_devuelve_inicial(repo, db):
    balance = repo.load_risk_state(ACCOUNT, 50_000.0, db)
    assert balance == 50_000.0


def test_save_y_load_risk_state(repo, db):
    repo.save_risk_state(ACCOUNT, 51_500.0, db)
    balance = repo.load_risk_state(ACCOUNT, 50_000.0, db)
    assert balance == 51_500.0


def test_save_risk_state_upsert(repo, db):
    """Guardar dos veces actualiza en lugar de insertar una fila nueva."""
    repo.save_risk_state(ACCOUNT, 51_000.0, db)
    repo.save_risk_state(ACCOUNT, 52_000.0, db)
    balance = repo.load_risk_state(ACCOUNT, 50_000.0, db)
    assert balance == 52_000.0


def test_risk_state_aislado_por_cuenta(repo, db):
    repo.save_risk_state(ACCOUNT, 51_000.0, db)
    repo.save_risk_state("otra_cuenta", 55_000.0, db)
    assert repo.load_risk_state(ACCOUNT, 50_000.0, db) == 51_000.0
    assert repo.load_risk_state("otra_cuenta", 50_000.0, db) == 55_000.0


# ------------------------------------------------------------------ #
# Cuentas
# ------------------------------------------------------------------ #

def _make_account(account_id: str, is_active: bool = True) -> Account:
    return Account(
        account_id=account_id,
        label=f"Cuenta {account_id}",
        tradovate_env="demo",
        secrets_key=f"/bot/{account_id}/tradovate",
        username=f"user_{account_id}@test.com",
        strategy="range_reversal_m15",
        symbol="MNQU6",
        point_value=2.0,
        initial_balance=50_000.0,
        max_drawdown=2_000.0,
        profit_target=3_000.0,
        consistency_pct=0.5,
        max_contracts=1,
        risk_pct=0.015,
        is_active=is_active,
    )


def test_get_active_accounts_devuelve_solo_activas(repo, db):
    db.add(_make_account("activa1"))
    db.add(_make_account("activa2"))
    db.add(_make_account("inactiva", is_active=False))
    db.commit()

    activas = repo.get_active_accounts(db)
    assert len(activas) == 2
    ids = {a.account_id for a in activas}
    assert ids == {"activa1", "activa2"}


def test_get_active_accounts_vacio(repo, db):
    assert repo.get_active_accounts(db) == []


def test_get_active_accounts_ordenadas_por_id(repo, db):
    db.add(_make_account("zzz"))
    db.add(_make_account("aaa"))
    db.commit()

    activas = repo.get_active_accounts(db)
    assert [a.account_id for a in activas] == ["aaa", "zzz"]

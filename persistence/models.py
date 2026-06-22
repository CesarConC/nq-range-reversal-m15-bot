from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import field_validator, model_validator
from sqlalchemy import CheckConstraint, Column, DateTime
from sqlmodel import Field, SQLModel

from persistence.common import (
    ExitReason,
    TradeStatus,
    ensure_tz_aware,
    generate_uid,
    now_utc,
    validate_account_id,
    validate_direction,
    validate_positive_float,
    validate_symbol,
    validate_uuid_str,
)


class Signal(SQLModel, table=True):
    """
    Cada señal que supera el filtro de riesgo y se intenta ejecutar.
    Se crea en Engine._handle_signal justo antes de enviar la orden.
    executed pasa a True solo si la orden llega al broker sin error.
    """
    __tablename__ = 'signal'

    uid: str = Field(
        default_factory=generate_uid,
        primary_key=True,
        index=True,
        description='Identificador unico de la señal (UUID4).',
    )
    ts: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
        description='Timestamp UTC en que se genero la señal.',
    )
    symbol: str = Field(
        nullable=False,
        description='Simbolo del instrumento negociado, ej. MNQU6.',
    )
    direction: str = Field(
        nullable=False,
        description='Direccion de la operacion: LONG o SHORT.',
    )
    entry_price: float = Field(
        nullable=False,
        description='Precio de entrada propuesto por la estrategia.',
    )
    take_profit: float = Field(
        nullable=False,
        description='Nivel de take profit calculado a partir del ratio RR.',
    )
    stop_loss: float = Field(
        nullable=False,
        description='Nivel de stop loss que define el riesgo de la operacion.',
    )
    executed: bool = Field(
        default=False,
        description='True si la orden llego al broker sin error. False si hubo un fallo de envio.',
    )

    # ------------------------------------------------------------------ #
    # Validadores de campo
    # ------------------------------------------------------------------ #

    @field_validator('uid')
    @classmethod
    def _validate_uid(cls, v: str) -> str:
        return validate_uuid_str(v, 'uid')

    @field_validator('symbol')
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        return validate_symbol(v)

    @field_validator('direction')
    @classmethod
    def _validate_direction(cls, v: str) -> str:
        return validate_direction(v)

    @field_validator('entry_price')
    @classmethod
    def _validate_entry_price(cls, v: float) -> float:
        return validate_positive_float(v, 'entry_price')

    @field_validator('take_profit')
    @classmethod
    def _validate_take_profit(cls, v: float) -> float:
        return validate_positive_float(v, 'take_profit')

    @field_validator('stop_loss')
    @classmethod
    def _validate_stop_loss(cls, v: float) -> float:
        return validate_positive_float(v, 'stop_loss')

    @field_validator('ts')
    @classmethod
    def _ensure_tz_aware_ts(cls, v: datetime) -> datetime:
        return ensure_tz_aware(v)

    # ------------------------------------------------------------------ #
    # Validador de modelo: coherencia entre direction, entry, tp y sl
    # ------------------------------------------------------------------ #

    @model_validator(mode='after')
    def _validate_levels(self) -> Signal:
        if self.direction == 'LONG':
            if self.take_profit <= self.entry_price:
                raise ValueError('LONG: take_profit debe estar por encima de entry_price')
            if self.stop_loss >= self.entry_price:
                raise ValueError('LONG: stop_loss debe estar por debajo de entry_price')
        else:
            if self.take_profit >= self.entry_price:
                raise ValueError('SHORT: take_profit debe estar por debajo de entry_price')
            if self.stop_loss <= self.entry_price:
                raise ValueError('SHORT: stop_loss debe estar por encima de entry_price')
        return self


class Trade(SQLModel, table=True):
    """
    Una fila por operacion. Se inserta al recibir el fill de entrada y se
    actualiza al recibir el fill de salida (TP o SL alcanzado).
    Cuando status pasa a CLOSED, exit_price y pnl deben estar informados.
    """
    __tablename__ = 'trade'
    __table_args__ = (
        CheckConstraint('qty > 0', name='ck_trade_qty_gt_0'),
        CheckConstraint('entry_price > 0', name='ck_trade_entry_price_gt_0'),
    )

    uid: str = Field(
        default_factory=generate_uid,
        primary_key=True,
        index=True,
        description='Identificador unico de la operacion (UUID4).',
    )
    account_id: str = Field(
        nullable=False,
        index=True,
        description='Identificador de la cuenta. Coincide con ACCOUNT_ID del entorno.',
    )
    signal_uid: Optional[str] = Field(
        default=None,
        foreign_key='signal.uid',
        nullable=True,
        description='UID de la señal que origino esta operacion. Puede ser None si el fill llego sin señal previa registrada.',
    )
    symbol: str = Field(
        nullable=False,
        description='Simbolo del instrumento negociado, ej. MNQU6.',
    )
    direction: str = Field(
        nullable=False,
        description='Direccion de la operacion: LONG o SHORT.',
    )
    qty: int = Field(
        nullable=False,
        description='Numero de contratos negociados.',
    )
    entry_price: float = Field(
        nullable=False,
        description='Precio al que se ejecuto el fill de entrada.',
    )
    entry_ts: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
        description='Timestamp UTC del fill de entrada.',
    )
    tp: Optional[float] = Field(
        default=None,
        nullable=True,
        description='Nivel de take profit enviado al broker. None si no se configuro.',
    )
    sl: Optional[float] = Field(
        default=None,
        nullable=True,
        description='Nivel de stop loss enviado al broker. None si no se configuro.',
    )
    exit_price: Optional[float] = Field(
        default=None,
        nullable=True,
        description='Precio al que se ejecuto el fill de salida. None mientras la operacion este abierta.',
    )
    exit_ts: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description='Timestamp UTC del fill de salida. None mientras la operacion este abierta.',
    )
    exit_reason: Optional[ExitReason] = Field(
        default=None,
        nullable=True,
        description='Motivo de cierre: ExitReason.TP, SL o MANUAL. None mientras este abierta.',
    )
    pnl: Optional[float] = Field(
        default=None,
        nullable=True,
        description='Resultado de la operacion en USD. Puede ser negativo. None hasta el cierre.',
    )
    status: TradeStatus = Field(
        default=TradeStatus.OPEN,
        description='Estado de la operacion: open mientras este en curso, closed tras el fill de salida.',
    )

    # ------------------------------------------------------------------ #
    # Validadores de campo
    # ------------------------------------------------------------------ #

    @field_validator('uid')
    @classmethod
    def _validate_uid(cls, v: str) -> str:
        return validate_uuid_str(v, 'uid')

    @field_validator('account_id')
    @classmethod
    def _validate_account_id(cls, v: str) -> str:
        return validate_account_id(v)

    @field_validator('signal_uid')
    @classmethod
    def _validate_signal_uid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return validate_uuid_str(v, 'signal_uid')

    @field_validator('symbol')
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        return validate_symbol(v)

    @field_validator('direction')
    @classmethod
    def _validate_direction(cls, v: str) -> str:
        return validate_direction(v)

    @field_validator('qty')
    @classmethod
    def _validate_qty(cls, v: int) -> int:
        if v <= 0:
            raise ValueError('qty must be greater than 0')
        return v

    @field_validator('entry_price')
    @classmethod
    def _validate_entry_price(cls, v: float) -> float:
        return validate_positive_float(v, 'entry_price')

    @field_validator('tp')
    @classmethod
    def _validate_tp(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return validate_positive_float(v, 'tp')
        return v

    @field_validator('sl')
    @classmethod
    def _validate_sl(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return validate_positive_float(v, 'sl')
        return v

    @field_validator('entry_ts')
    @classmethod
    def _ensure_tz_aware_entry(cls, v: datetime) -> datetime:
        return ensure_tz_aware(v)

    @field_validator('exit_ts')
    @classmethod
    def _ensure_tz_aware_exit(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        return ensure_tz_aware(v)

    # ------------------------------------------------------------------ #
    # Validador de modelo: coherencia del estado CLOSED
    # ------------------------------------------------------------------ #

    @model_validator(mode='after')
    def _validate_closed_state(self) -> Trade:
        if self.status == TradeStatus.CLOSED:
            if self.exit_price is None:
                raise ValueError('exit_price es obligatorio cuando status es CLOSED')
            if self.pnl is None:
                raise ValueError('pnl es obligatorio cuando status es CLOSED')
            if self.exit_ts is not None and self.exit_ts < self.entry_ts:
                raise ValueError('exit_ts no puede ser anterior a entry_ts')
        return self


class RiskState(SQLModel, table=True):
    """
    Una fila por cuenta. Persiste max_eod_balance entre sesiones del bot,
    reemplazando el antiguo risk_state.json. Se actualiza al final de cada
    dia de trading via TradeRepository.save_risk_state().
    """
    __tablename__ = 'risk_state'

    account_id: str = Field(
        primary_key=True,
        description='Identificador unico de la cuenta. Coincide con ACCOUNT_ID del entorno.',
    )
    max_eod_balance: float = Field(
        nullable=False,
        description='Balance maximo EOD alcanzado historicamente. Base del trailing drawdown.',
    )
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
        description='Timestamp UTC de la ultima actualizacion.',
    )

    @field_validator('account_id')
    @classmethod
    def _validate_account_id(cls, v: str) -> str:
        return validate_account_id(v)

    @field_validator('max_eod_balance')
    @classmethod
    def _validate_max_eod_balance(cls, v: float) -> float:
        return validate_positive_float(v, 'max_eod_balance')

    @field_validator('updated_at')
    @classmethod
    def _ensure_tz_aware_updated_at(cls, v: datetime) -> datetime:
        return ensure_tz_aware(v)

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ------------------------------------------------------------------ #
# Timestamps
# ------------------------------------------------------------------ #

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_tz_aware(dt: datetime) -> datetime:
    """Añade tzinfo UTC si el datetime no tiene zona horaria."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ------------------------------------------------------------------ #
# Identificadores
# ------------------------------------------------------------------ #

def generate_uid() -> str:
    """Genera un UUID4 como string. Se usa como default_factory en las PKs."""
    return str(uuid.uuid4())


def validate_uuid_str(value: str, field_name: str = 'uid') -> str:
    """Valida que el string sea un UUID bien formado."""
    import uuid as _uuid
    value = value.strip()
    try:
        _uuid.UUID(value)
    except ValueError:
        raise ValueError(f'{field_name} must be a valid UUID string')
    return value


# ------------------------------------------------------------------ #
# Strings
# ------------------------------------------------------------------ #

def normalize_optional_str(value: Optional[str]) -> Optional[str]:
    """Elimina espacios; devuelve None si el resultado queda vacio."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def validate_account_id(value: str) -> str:
    """Exige que el account_id no este vacio."""
    value = value.strip()
    if not value:
        raise ValueError('account_id cannot be blank')
    return value


def validate_symbol(value: str) -> str:
    """Elimina espacios y exige que el simbolo no este vacio."""
    value = value.strip()
    if not value:
        raise ValueError('symbol cannot be blank')
    return value


def validate_direction(value: str) -> str:
    """Exige que la direccion sea exactamente LONG o SHORT."""
    if value not in ('LONG', 'SHORT'):
        raise ValueError("direction must be 'LONG' or 'SHORT'")
    return value


# ------------------------------------------------------------------ #
# Numericos
# ------------------------------------------------------------------ #

def validate_positive_float(value: float, field_name: str = 'value') -> float:
    """Exige que el float sea estrictamente positivo."""
    if value <= 0:
        raise ValueError(f'{field_name} must be greater than 0')
    return value


# ------------------------------------------------------------------ #
# Enums
# ------------------------------------------------------------------ #

class TradeStatus(str, Enum):
    OPEN = 'open'
    CLOSED = 'closed'


class ExitReason(str, Enum):
    TP = 'TP'
    SL = 'SL'
    MANUAL = 'MANUAL'

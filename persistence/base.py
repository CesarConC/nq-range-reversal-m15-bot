from sqlmodel import SQLModel

from persistence.models import Account, RiskState, Signal, Trade  # noqa: F401

Base = SQLModel
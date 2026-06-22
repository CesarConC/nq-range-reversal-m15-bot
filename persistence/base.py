from sqlmodel import SQLModel

from persistence.models import RiskState, Signal, Trade  # noqa: F401

Base = SQLModel

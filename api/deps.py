"""Dependencias FastAPI reutilizables."""
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, Path
from sqlmodel import Session

from core.registry import BotController, controllers
from persistence.session import get_session as _get_session


def _get_controller(account_id: str = Path(...)) -> BotController:
    ctrl = controllers.get(account_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    return ctrl


def _get_db() -> Generator[Session, None, None]:
    with _get_session() as db:
        yield db


ControllerDep = Annotated[BotController, Depends(_get_controller)]
SessionDep = Annotated[Session, Depends(_get_db)]
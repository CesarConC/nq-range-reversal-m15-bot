"""
Autenticacion REST contra Tradovate: login inicial y renovacion de token.

Endpoint usado: POST /auth/accesstokenrequest
Body esperado por Tradovate: {name, password, appId, appVersion, cid, sec, deviceId}
Respuesta: {accessToken, mdAccessToken, expirationTime, userId, hasMarketData, ...}

El accessToken se usa para llamadas REST normales (ordenes, cuenta) y para
el websocket de usuario. El mdAccessToken se usa para autorizar el
websocket de market data (md.tradovateapi.com).
"""
import logging

import httpx

from config.settings import TradovateConfig
from tradovate.models import AuthSession

logger = logging.getLogger(__name__)


class TradovateAuth:
    def __init__(self, config: TradovateConfig):
        self.config = config
        self.session: AuthSession | None = None

    async def login(self) -> AuthSession:
        url = f"{self.config.rest_base_url}/auth/accesstokenrequest"
        payload = {
            "name": self.config.username,
            "password": self.config.password,
            "appId": self.config.app_id,
            "appVersion": self.config.app_version,
            "cid": self.config.cid,
            "sec": self.config.secret,
            "deviceId": self.config.device_id,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "errorText" in data:
            raise RuntimeError(f"Tradovate rechazo el login: {data['errorText']}")

        self.session = AuthSession(
            access_token=data["accessToken"],
            md_access_token=data.get("mdAccessToken"),
            expiration_time=data["expirationTime"],
            user_id=data["userId"],
            has_market_data=data.get("hasMarketData", False),
            has_funded=data.get("hasFunded", False),
        )

        logger.info(
            "Login OK -> userId=%s entorno=%s hasMarketData=%s hasFunded=%s",
            self.session.user_id,
            self.config.environment,
            self.session.has_market_data,
            self.session.has_funded,
        )
        return self.session

    async def renew(self) -> AuthSession:
        """Renueva el access token antes de que expire. Llamar periodicamente
        (ej. cada 60-70% del tiempo de vida del token) en vez de loguear de nuevo."""
        if not self.session:
            return await self.login()

        url = f"{self.config.rest_base_url}/auth/renewaccesstoken"
        headers = {"Authorization": f"Bearer {self.session.access_token}"}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        self.session.access_token = data["accessToken"]
        self.session.expiration_time = data["expirationTime"]
        logger.info("Token renovado. Nueva expiracion: %s", self.session.expiration_time)
        return self.session

# tradovate_bot

Bot de trading para MNQ (CME) sobre cuentas fondeadas via Tradovate.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con:
- Tu usuario/password de Tradovate
- Tu `cid` y `secret` (se generan en Tradovate > Settings > API Access; requiere
  la suscripcion del API add-on, ~$25/mes, y pasar el proceso de auto-atestacion)
- Deja `TRADOVATE_ENV=demo` para todo el desarrollo

## Primer milestone: ver quotes de MNQ en vivo

```bash
python -m scripts.run_paper
```

Esto hace login contra el entorno demo, abre el websocket de market data,
se suscribe a MNQ y va imprimiendo bid/ask/last en consola.

**Antes de correrlo**, revisa `MNQ_SYMBOL` en `scripts/run_paper.py` — Tradovate
necesita el contrato especifico (ej. `MNQU6`), no el ticker generico `MNQ`.
Puedes confirmar el contrato vigente en la plataforma de Tradovate o
consultando `GET /contract/find?name=MNQ` por REST.

## Estructura del proyecto

```
config/         configuracion y variables de entorno
tradovate/      auth, cliente REST, cliente WebSocket (capa de conexion pura)
market_data/    suscripcion a quotes, normalizacion a objetos Quote
strategy/       tu logica de trading (BaseStrategy + MyStrategy)
risk/           validacion de reglas de la cuenta fondeada antes de cada orden
execution/      envio de ordenes reales y tracking de fills
core/           engine que orquesta todo + estado de cuenta en memoria
persistence/    guardado de señales/ordenes/fills para auditoria
monitoring/     logging y alertas (Telegram/Discord)
backtesting/    correr la misma estrategia contra datos historicos
scripts/        puntos de entrada: run_paper.py, run_live.py, run_backtest.py
```

## Estado actual

- [x] Conexion REST + WebSocket a Tradovate (demo)
- [x] Suscripcion y recepcion de quotes en vivo de MNQ
- [ ] Implementar `strategy/my_strategy.py` con la logica real
- [ ] Completar `risk/risk_manager.py` con las reglas exactas del fondeo
- [ ] Completar `execution/order_manager.py` y `core/engine.py`
- [ ] Validar en demo de forma prolongada antes de tocar `run_live.py`

## Notas importantes

- El protocolo WebSocket de Tradovate (framing tipo SockJS) no esta 100%
  documentado en un solo lugar. Si algo falla al conectar, compara contra
  el repo oficial `tradovate/example-api-js`.
- Nunca commitear el archivo `.env` real.
- Verifica las reglas de tu programa de fondeo sobre trading automatizado
  antes de pasar a `run_live.py`.

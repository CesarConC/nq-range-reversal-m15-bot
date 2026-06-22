# nq-range-reversal-m15-bot

Bot de trading algorítmico para futuros MNQ/NQ (CME) sobre cuentas fondeadas via Tradovate.

**Estrategia:** reversión en rango M15 con confirmación de vela engulfing en M1.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # rellena tus credenciales
```

## Variables de entorno

### Credenciales Tradovate (requeridas)

| Variable | Descripcion |
|---|---|
| `TRADOVATE_ENV` | `demo` (desarrollo) o `live` (produccion). Default: `demo` |
| `TRADOVATE_USERNAME` | Usuario de tu cuenta Tradovate |
| `TRADOVATE_PASSWORD` | Password de tu cuenta Tradovate |
| `TRADOVATE_CID` | Client ID del API add-on (~$25/mes, requiere auto-atestacion) |
| `TRADOVATE_SECRET` | Secret del API add-on |
| `TRADOVATE_APP_ID` | Nombre de tu app. Default: `MyTradingBot` |
| `TRADOVATE_APP_VERSION` | Version de tu app. Default: `1.0` |
| `TRADOVATE_DEVICE_ID` | Identificador del dispositivo. Default: `bot-device-001` |

### Parametros del bot (todos con valores por defecto)

| Variable | Default | Descripcion |
|---|---|---|
| `SYMBOL` | `MNQU6` | Contrato activo (verificar en Tradovate el vencimiento vigente) |
| `POINT_VALUE` | `2.0` | USD por punto: MNQ=2.0, NQ=20.0 |
| `INITIAL_BALANCE` | `50000.0` | Balance inicial de la cuenta fondeada |
| `MAX_DRAWDOWN` | `2000.0` | Drawdown maximo permitido (USD) |
| `PROFIT_TARGET` | `3000.0` | Objetivo de beneficio (USD) |
| `CONSISTENCY_PCT` | `0.5` | Ningun dia puede superar este porcentaje del objetivo |
| `MAX_CONTRACTS` | `1` | Maximo de contratos por operacion |
| `RISK_PCT` | `0.015` | Riesgo por operacion (1.5% del balance inicial) |
| `RR_RATIO` | `0.33` | Ratio reward/risk (reward = 0.33 × risk) |
| `HEARTBEAT_INTERVAL` | `2.5` | Segundos entre heartbeats al WebSocket de Tradovate |
| `RISK_STATE_PATH` | `risk_state.json` | Fichero para persistir el estado de riesgo entre sesiones |
| `DB_PATH` | `bot.db` | Ruta del fichero SQLite |
| `DATABASE_URL` | *(calculado de DB_PATH)* | URL completa de conexion. Sobreescribir para usar otro motor |

## Ejecutar en demo

```bash
python -m scripts.run_paper
```

Arranca el bot completo contra el entorno demo de Tradovate: market data en vivo,
velas M1/M15, estrategia, risk manager y envio de ordenes reales (en demo).

> Verifica que `SYMBOL` en tu `.env` corresponde al contrato frontal vigente.
> Puedes confirmarlo en la plataforma de Tradovate o via `GET /contract/find?name=MNQ`.

## Tests

```bash
pytest
```

67 tests unitarios cubriendo estrategia, agregador de velas, engine, risk manager,
estado de cuenta y repositorio de persistencia.

## Estructura del proyecto

```
config/          configuracion central (settings, instancias compartidas)
tradovate/       auth, cliente REST y WebSocket (capa de conexion pura)
market_data/     suscripcion a quotes y agregacion de velas (M1, M15)
strategy/        logica de trading: BaseStrategy + MyStrategy (rango reversal)
risk/            validacion de reglas de cuenta fondeada antes de cada orden
execution/       envio de ordenes bracket (TP/SL) a Tradovate
core/            engine principal + estado de cuenta en memoria
persistence/     señales y operaciones en SQLite (SQLModel/SQLAlchemy)
account_data/    socket de usuario: fills, ordenes y posiciones en tiempo real
monitoring/      logging y alertas
backtesting/     correr la estrategia contra datos historicos
scripts/         puntos de entrada: run_paper.py, run_live.py, run_backtest.py
tests/           suite de tests unitarios
```

## Estado actual

- [x] Conexion REST + WebSocket a Tradovate (demo y live)
- [x] Suscripcion y recepcion de quotes en vivo
- [x] Agregador de velas M1 y M15
- [x] Estrategia de rango reversal M15 con confirmacion engulfing M1
- [x] Risk manager con reglas de cuenta fondeada
- [x] Order manager: entrada con bracket TP/SL
- [x] Engine principal que orquesta todo el flujo
- [x] Estado de cuenta en memoria (posicion, PnL, fills)
- [x] Socket de usuario: fills y posiciones en tiempo real
- [x] Persistencia de señales y operaciones en SQLite
- [ ] Backtesting contra datos historicos
- [ ] Validacion prolongada en demo antes de activar `run_live.py`

## Notas importantes

- Nunca commitear el archivo `.env` real.
- El protocolo WebSocket de Tradovate usa framing SockJS. Si algo falla al
  conectar, compara contra el repo oficial `tradovate/example-api-js`.
- Verifica las reglas de tu programa de fondeo sobre trading automatizado
  antes de pasar a `run_live.py`.

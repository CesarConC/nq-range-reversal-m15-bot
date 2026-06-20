from datetime import datetime, timedelta, timezone

from strategy.my_strategy import MyStrategy
from tradovate.models import Candle


def make_candle(o, h, l, c, minutes_offset=0, timeframe="M1"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes_offset)
    return Candle(
        timeframe=timeframe,
        open_time=start,
        close_time=start + timedelta(minutes=1 if timeframe == "M1" else 15),
        open=o, high=h, low=l, close=c,
    )


def make_range(low, high):
    """Crea una estrategia con un rango M15 ya activo [low, high]."""
    strat = MyStrategy()
    range_candle = make_candle(o=(low + high) / 2, h=high, l=low, c=(low + high) / 2, timeframe="M15")
    strat.on_m15_close(range_candle)
    return strat


def test_ejemplo_conversacion_short_con_objetivo_movil():
    """Replica el ejemplo: el high se toma dos veces (el segundo mas lejos),
    la envolvente debe ser sobre la SEGUNDA vela, no la primera, y la
    entrada se dispara cuando finalmente cierra dentro del rango."""
    strat = make_range(low=21300, high=21350)

    # M1 #1: toma el high por primera vez
    c1 = make_candle(o=21348, h=21355, l=21347, c=21352, minutes_offset=1)
    assert strat.on_m1_close(c1) is None

    # M1 #2: hace un extremo MAS lejano -> se convierte en la nueva vela_extremo
    c2 = make_candle(o=21352, h=21362, l=21351, c=21358, minutes_offset=2)
    assert strat.on_m1_close(c2) is None

    # M1 #3: su cuerpo envuelve a #2 (body 21351-21358), pero cierra FUERA del rango (21345... espera, debe ser >21350 para seguir fuera)
    c3 = make_candle(o=21360, h=21361, l=21351, c=21351, minutes_offset=3)
    # cuerpo de c3 = [21351, 21360] cubre cuerpo de c2 = [21352, 21358] -> envuelve
    assert strat.on_m1_close(c3) is None  # cierra en 21351, todavia fuera del rango (>21350)

    # M1 #4: cierra dentro del rango (21340), engullida ya estaba en True -> ENTRA SHORT
    c4 = make_candle(o=21345, h=21346, l=21338, c=21340, minutes_offset=4)
    signal = strat.on_m1_close(c4)

    assert signal is not None
    assert signal.direction == "SHORT"
    assert signal.entry_price == 21340
    assert signal.take_profit == 21300  # el otro extremo del rango
    reward = signal.entry_price - signal.take_profit
    risk = signal.stop_loss - signal.entry_price
    assert round(risk / reward, 2) == round(1 / 0.33, 2)


def test_ambos_extremos_tomados_no_opera():
    strat = make_range(low=21300, high=21350)

    # se toma el low primero -> bloquea direccion LONG
    c1 = make_candle(o=21302, h=21303, l=21295, c=21301, minutes_offset=1)
    assert strat.on_m1_close(c1) is None

    # antes de completar la entrada, se toma el high (extremo contrario) -> descarta TODO
    c2 = make_candle(o=21349, h=21355, l=21348, c=21352, minutes_offset=2)
    assert strat.on_m1_close(c2) is None

    # cualquier vela posterior ya no puede disparar nada en este rango
    c3 = make_candle(o=21320, h=21321, l=21319, c=21320, minutes_offset=3)
    assert strat.on_m1_close(c3) is None


def test_retoque_sin_superar_extremo_no_actualiza_objetivo():
    strat = make_range(low=21300, high=21350)

    # toma el low con una mecha profunda
    c1 = make_candle(o=21302, h=21303, l=21290, c=21301, minutes_offset=1)
    assert strat.on_m1_close(c1) is None

    # retoca el low pero NO supera 21290 -> no cambia la vela_extremo
    c2 = make_candle(o=21298, h=21299, l=21295, c=21297, minutes_offset=2)
    assert strat.on_m1_close(c2) is None

    # esta vela envuelve el cuerpo de c1 (21301 a 21302) y cierra dentro del rango
    c3 = make_candle(o=21296, h=21306, l=21295, c=21305, minutes_offset=3)
    signal = strat.on_m1_close(c3)

    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.take_profit == 21350


def test_engulfing_y_cierre_dentro_en_la_misma_vela_simple():
    """Caso simple: una sola vela hace sweep+vuelta, la siguiente envuelve y cierra dentro."""
    strat = make_range(low=21300, high=21350)

    sweep = make_candle(o=21302, h=21303, l=21290, c=21298, minutes_offset=1)
    assert strat.on_m1_close(sweep) is None  # es la vela_extremo, no puede disparar

    confirm = make_candle(o=21297, h=21310, l=21296, c=21308, minutes_offset=2)
    # cuerpo confirm = [21297, 21308] cubre cuerpo sweep = [21298, 21302] -> envuelve
    # y cierra en 21308, dentro del rango -> entra
    signal = strat.on_m1_close(confirm)

    assert signal is not None
    assert signal.direction == "LONG"
    assert signal.entry_price == 21308
    assert signal.take_profit == 21350


def test_no_se_opera_si_no_se_toma_ningun_extremo():
    strat = make_range(low=21300, high=21350)
    inside = make_candle(o=21320, h=21330, l=21310, c=21325, minutes_offset=1)
    assert strat.on_m1_close(inside) is None


def test_m15_close_rota_el_rango_siempre():
    strat = make_range(low=21300, high=21350)
    nuevo_rango = make_candle(o=21340, h=21380, l=21335, c=21360, timeframe="M15", minutes_offset=15)
    strat.on_m15_close(nuevo_rango)
    assert strat._range.range_low == 21335
    assert strat._range.range_high == 21380


# --- Tests agregados en la revision de codigo ---

def test_bug1_una_vela_toma_ambos_extremos_a_la_vez_descarta():
    """Bug encontrado en revision: si una sola M1 tiene low < range_low Y
    high > range_high y no hay direccion bloqueada, el rango debe
    descartarse. Antes del fix, el codigo silenciosamente bloqueaba
    LONG (porque el low se chequeaba primero) e ignoraba el high."""
    strat = make_range(low=21300, high=21350)

    monster = make_candle(o=21320, h=21360, l=21290, c=21310, minutes_offset=1)
    assert strat.on_m1_close(monster) is None
    assert strat._range.resolved is True  # rango descartado

    # nada posterior puede disparar señal
    c2 = make_candle(o=21310, h=21311, l=21309, c=21310, minutes_offset=2)
    assert strat.on_m1_close(c2) is None


def test_ambos_extremos_simultaneos_con_direccion_ya_bloqueada():
    """Si ya hay direccion bloqueada (ej. LONG) y una nueva vela toma ambos
    extremos, el check del extremo contrario (high) debe descartar."""
    strat = make_range(low=21300, high=21350)

    # toma el low primero (vela normal) -> bloquea LONG
    c1 = make_candle(o=21302, h=21303, l=21295, c=21301, minutes_offset=1)
    strat.on_m1_close(c1)

    # otra vela toma AMBOS extremos -> el high invalida el rango
    c2 = make_candle(o=21320, h=21360, l=21290, c=21310, minutes_offset=2)
    assert strat.on_m1_close(c2) is None
    assert strat._range.resolved is True


def test_engulfing_sin_color_correcto_no_dispara():
    """La envolvente debe tener color coherente con la direccion (alcista
    para LONG, bajista para SHORT). Una envolvente roja en un setup LONG
    no debe disparar señal."""
    strat = make_range(low=21300, high=21350)

    # sweep del low -> bloquea LONG
    sweep = make_candle(o=21302, h=21303, l=21290, c=21298, minutes_offset=1)
    strat.on_m1_close(sweep)

    # envolvente BAJISTA (open > close) en un setup LONG -> no cuenta
    engulf_wrong = make_candle(o=21310, h=21311, l=21295, c=21296, minutes_offset=2)
    # cuerpo = [21296, 21310] cubre cuerpo sweep = [21298, 21302] -> tamaño OK
    # pero es bajista en un setup LONG -> no debe contar
    assert strat.on_m1_close(engulf_wrong) is None
    assert strat._range.engulfed is False  # no se marco como engullida


def test_signal_con_reward_cero_no_se_emite():
    """Si el precio de entrada coincide con el TP, reward=0 y la señal
    no debe emitirse."""
    strat = make_range(low=21300, high=21350)

    # sweep del high -> bloquea SHORT, TP seria 21300
    sweep = make_candle(o=21348, h=21355, l=21347, c=21352, minutes_offset=1)
    strat.on_m1_close(sweep)

    # envolvente correcta (bajista) y cierra EXACTO en el TP (21300)
    engulf = make_candle(o=21360, h=21361, l=21299, c=21350, minutes_offset=2)
    strat.on_m1_close(engulf)

    trigger = make_candle(o=21305, h=21306, l=21298, c=21300, minutes_offset=3)
    signal = strat.on_m1_close(trigger)
    # entry=21300, tp=21300, reward=0 -> no se opera
    assert signal is None

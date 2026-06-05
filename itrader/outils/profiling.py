import time
from typing import Any


def speed(ticks: float, t0: float) -> float:
    return ticks / (time.time() - t0)


def s_speed(time_event: Any, ticks: int, t0: float) -> str:
    sp = speed(ticks, t0)
    s_typ = time_event.typename + "S"
    return "%d %s processed @ %f %s/s" % (ticks, s_typ, sp, s_typ)

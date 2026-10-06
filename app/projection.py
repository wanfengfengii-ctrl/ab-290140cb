"""Projection of score cue ticks onto the audio sample clock.

All cumulative time is kept as an exact rational number of microseconds
(:class:`fractions.Fraction`) so no rounding error accumulates across tempo
segments. Only at the very end are the nanosecond timestamp and the
zero-based sample frame derived, each rounded independently from the
unrounded cumulative duration using round-half-even.
"""
from bisect import bisect_right
from fractions import Fraction

from .validation import HOLD, validate_request

_MICROS_PER_SECOND = 1_000_000
_NANOS_PER_MICRO = 1_000


class TempoMap:
    """Piecewise tempo curve with exact cumulative-time lookup.

    Segment ``i`` spans ``[tick_i, tick_{i+1})`` and follows the mode of
    point ``i``: ``hold`` keeps the tempo constant, ``ramp`` interpolates it
    linearly in ticks towards the next point. Past the last point the last
    tempo holds constant.
    """

    def __init__(self, points, ticks_per_quarter):
        self._points = points
        self._ppq = ticks_per_quarter
        self._ticks = [p["tick"] for p in points]
        # prefix[i] == exact cumulative microseconds at self._ticks[i].
        self._prefix = [Fraction(0)]
        for i in range(len(points) - 1):
            self._prefix.append(self._prefix[-1] + self._segment_micros(i, points[i + 1]["tick"]))

    def _segment_micros(self, i, upto_tick):
        """Exact microseconds elapsed between tick_i and ``upto_tick``."""
        point = self._points[i]
        dt = upto_tick - point["tick"]
        if dt <= 0:
            return Fraction(0)
        tau0 = point["microsPerQuarter"]
        if point["mode"] == HOLD or i == len(self._points) - 1:
            return Fraction(tau0 * dt, self._ppq)
        # Ramp: tempo moves linearly in ticks from tau0 to tau1, so the
        # integral of tau0 + (tau1 - tau0) * x / width over x in [0, dt].
        tau1 = self._points[i + 1]["microsPerQuarter"]
        width = self._points[i + 1]["tick"] - point["tick"]
        return Fraction(tau0 * dt, self._ppq) + Fraction(
            (tau1 - tau0) * dt * dt, 2 * width * self._ppq
        )

    def micros_at(self, tick):
        """Exact cumulative microseconds from tick 0 to ``tick``."""
        i = bisect_right(self._ticks, tick) - 1  # ticks[0] == 0, tick >= 0
        return self._prefix[i] + self._segment_micros(i, tick)


def project(payload):
    """Validate ``payload`` and return one projection per cue, in order."""
    data = validate_request(payload)
    tempo_map = TempoMap(data["tempoPoints"], data["ticksPerQuarter"])
    sample_rate = data["sampleRate"]

    projections = []
    for cue in data["cues"]:
        micros = tempo_map.micros_at(cue["tick"])
        # round() on Fraction is round-half-even; both values are derived
        # independently from the same unrounded cumulative duration.
        nanoseconds = round(micros * _NANOS_PER_MICRO)
        frame = round(micros * sample_rate / _MICROS_PER_SECOND)
        projections.append(
            {
                "id": cue["id"],
                "tick": cue["tick"],
                "nanoseconds": nanoseconds,
                "frame": frame,
            }
        )
    return projections

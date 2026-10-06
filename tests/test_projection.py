"""Core projection math: hold segments, ramp segments, exact rounding."""
import unittest
from fractions import Fraction

from app.projection import project


def reference_micros(points, ppq, tick):
    """Independent exact-arithmetic reference implementation."""
    total = Fraction(0)
    for i in range(len(points) - 1):
        t0, t1 = points[i]["tick"], points[i + 1]["tick"]
        if tick <= t0:
            return total
        dt = min(tick, t1) - t0
        if points[i]["mode"] == "hold":
            total += Fraction(points[i]["microsPerQuarter"] * dt, ppq)
        else:
            tau0 = points[i]["microsPerQuarter"]
            tau1 = points[i + 1]["microsPerQuarter"]
            total += Fraction(tau0 * dt, ppq) + Fraction(
                (tau1 - tau0) * dt * dt, 2 * (t1 - t0) * ppq
            )
        if tick <= t1:
            return total
    last = points[-1]
    if tick > last["tick"]:
        total += Fraction(last["microsPerQuarter"] * (tick - last["tick"]), ppq)
    return total


class HoldSegmentsTest(unittest.TestCase):
    def test_single_hold_point(self):
        result = project({
            "ticksPerQuarter": 480,
            "sampleRate": 48000,
            "tempoPoints": [{"tick": 0, "microsPerQuarter": 500000, "mode": "hold"}],
            "cues": [
                {"id": "a", "tick": 0},
                {"id": "b", "tick": 240},
                {"id": "c", "tick": 480},
                {"id": "d", "tick": 960},
            ],
        })
        self.assertEqual(
            [p["nanoseconds"] for p in result],
            [0, 250_000_000, 500_000_000, 1_000_000_000],
        )
        self.assertEqual([p["frame"] for p in result], [0, 12000, 24000, 48000])

    def test_tempo_change_between_hold_segments(self):
        result = project({
            "ticksPerQuarter": 480,
            "sampleRate": 48000,
            "tempoPoints": [
                {"tick": 0, "microsPerQuarter": 500000, "mode": "hold"},
                {"tick": 480, "microsPerQuarter": 250000, "mode": "hold"},
            ],
            "cues": [{"id": "x", "tick": 480}, {"id": "y", "tick": 960}],
        })
        # 480 ticks at 500000 us/quarter, then 480 more at 250000 us/quarter.
        self.assertEqual(result[0]["nanoseconds"], 500_000_000)
        self.assertEqual(result[1]["nanoseconds"], 750_000_000)
        self.assertEqual(result[1]["frame"], 36000)


class RampSegmentsTest(unittest.TestCase):
    def test_ramp_then_hold_tail(self):
        result = project({
            "ticksPerQuarter": 480,
            "sampleRate": 48000,
            "tempoPoints": [
                {"tick": 0, "microsPerQuarter": 500000, "mode": "ramp"},
                {"tick": 960, "microsPerQuarter": 250000, "mode": "hold"},
            ],
            "cues": [
                {"id": "mid", "tick": 480},
                {"id": "end", "tick": 960},
                {"id": "tail", "tick": 1440},
            ],
        })
        # Mid-ramp: average of 500000 and 375000 over one quarter.
        self.assertEqual(result[0]["nanoseconds"], 437_500_000)
        # Full ramp: average of endpoints over two quarters.
        self.assertEqual(result[1]["nanoseconds"], 750_000_000)
        # Past the last point the last tempo holds constant.
        self.assertEqual(result[2]["nanoseconds"], 1_000_000_000)
        self.assertEqual(result[2]["frame"], 48000)

    def test_ramp_downwards_partial_tick(self):
        # Tempo glides 600000 -> 300000 over 480 ticks; probe a mid tick.
        result = project({
            "ticksPerQuarter": 480,
            "sampleRate": 96000,
            "tempoPoints": [
                {"tick": 0, "microsPerQuarter": 600000, "mode": "ramp"},
                {"tick": 480, "microsPerQuarter": 300000, "mode": "hold"},
            ],
            "cues": [{"id": "q", "tick": 120}],
        })
        # tau(120) = 525000; integral = (600000 + 525000) / 2 * 120/480 us.
        self.assertEqual(result[0]["nanoseconds"], 140_625_000)
        self.assertEqual(result[0]["frame"], 13500)


class RoundingTest(unittest.TestCase):
    def test_nanoseconds_round_half_even(self):
        # 1 us/quarter at 2000 ticks/quarter -> exactly 0.5 ns per tick.
        result = project({
            "ticksPerQuarter": 2000,
            "sampleRate": 1_000_000_000,
            "tempoPoints": [{"tick": 0, "microsPerQuarter": 1, "mode": "hold"}],
            "cues": [{"id": str(t), "tick": t} for t in (1, 2, 3, 4, 5)],
        })
        # 0.5 -> 0, 1.0 -> 1, 1.5 -> 2, 2.0 -> 2, 2.5 -> 2 (ties to even).
        self.assertEqual([p["nanoseconds"] for p in result], [0, 1, 2, 2, 2])

    def test_frames_round_half_even_independently(self):
        # 625/60 us per tick; at 48000 Hz that is exactly 0.5 frames per tick.
        result = project({
            "ticksPerQuarter": 60,
            "sampleRate": 48000,
            "tempoPoints": [{"tick": 0, "microsPerQuarter": 625, "mode": "hold"}],
            "cues": [{"id": str(t), "tick": t} for t in (1, 3, 5, 7)],
        })
        self.assertEqual([p["frame"] for p in result], [0, 2, 2, 4])

    def test_no_accumulated_rounding_across_many_segments(self):
        # 500 ramp/hold segments with tempos that produce repeating decimals;
        # an implementation accumulating floats would drift here.
        points = []
        for i in range(500):
            points.append({
                "tick": i * 7,
                "microsPerQuarter": 1000 + (i % 13),
                "mode": "ramp" if i % 2 == 0 else "hold",
            })
        cues = [{"id": str(t), "tick": t} for t in range(0, 500 * 7, 11)]
        result = project({
            "ticksPerQuarter": 96,
            "sampleRate": 192000,
            "tempoPoints": points,
            "cues": cues,
        })
        for got, cue in zip(result, cues):
            micros = reference_micros(points, 96, cue["tick"])
            self.assertEqual(got["nanoseconds"], round(micros * 1000), cue)
            self.assertEqual(got["frame"], round(micros * 192000 / 1_000_000), cue)


class CueHandlingTest(unittest.TestCase):
    def test_same_tick_same_projection_and_order_preserved(self):
        result = project({
            "ticksPerQuarter": 480,
            "sampleRate": 48000,
            "tempoPoints": [{"tick": 0, "microsPerQuarter": 500000, "mode": "hold"}],
            "cues": [
                {"id": "late", "tick": 960},
                {"id": "early", "tick": 480},
                {"id": "also-early", "tick": 480},
            ],
        })
        self.assertEqual([p["id"] for p in result], ["late", "early", "also-early"])
        self.assertEqual(result[1]["nanoseconds"], result[2]["nanoseconds"])
        self.assertEqual(result[1]["frame"], result[2]["frame"])

    def test_mixed_map_matches_reference(self):
        points = [
            {"tick": 0, "microsPerQuarter": 500000, "mode": "ramp"},
            {"tick": 1920, "microsPerQuarter": 400000, "mode": "hold"},
            {"tick": 3840, "microsPerQuarter": 600000, "mode": "ramp"},
            {"tick": 4800, "microsPerQuarter": 300000, "mode": "hold"},
        ]
        cues = [{"id": str(t), "tick": t} for t in range(0, 6001, 137)]
        result = project({
            "ticksPerQuarter": 480,
            "sampleRate": 44100,
            "tempoPoints": points,
            "cues": cues,
        })
        for got, cue in zip(result, cues):
            micros = reference_micros(points, 480, cue["tick"])
            self.assertEqual(got["nanoseconds"], round(micros * 1000), cue)
            self.assertEqual(got["frame"], round(micros * 44100 / 1_000_000), cue)


if __name__ == "__main__":
    unittest.main()

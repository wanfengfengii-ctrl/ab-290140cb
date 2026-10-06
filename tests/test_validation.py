"""Stable error codes and positions; all-or-nothing validation."""
import copy
import unittest

from app.errors import ApiError
from app.projection import project

BASE = {
    "ticksPerQuarter": 480,
    "sampleRate": 48000,
    "tempoPoints": [{"tick": 0, "microsPerQuarter": 500000, "mode": "hold"}],
    "cues": [{"id": "a", "tick": 0}],
}


def mutated(fn):
    payload = copy.deepcopy(BASE)
    fn(payload)
    return payload


class ErrorCaseTest(unittest.TestCase):
    def assert_error(self, payload, code, status=422, index=None, path=None):
        with self.assertRaises(ApiError) as ctx:
            project(payload)
        err = ctx.exception
        self.assertEqual(err.code, code)
        self.assertEqual(err.status, status)
        if index is not None:
            self.assertEqual(err.position.get("index"), index)
        if path is not None:
            self.assertEqual(err.position.get("path"), path)

    def test_tempo_map_must_start_at_zero(self):
        self.assert_error(
            mutated(lambda p: p["tempoPoints"].__setitem__(
                0, {"tick": 10, "microsPerQuarter": 500000, "mode": "hold"})),
            "TEMPO_MAP_GAP", index=0, path="tempoPoints[0].tick",
        )

    def test_duplicate_tick(self):
        def edit(p):
            p["tempoPoints"] = [
                {"tick": 0, "microsPerQuarter": 500000, "mode": "hold"},
                {"tick": 480, "microsPerQuarter": 500000, "mode": "hold"},
                {"tick": 480, "microsPerQuarter": 400000, "mode": "hold"},
            ]
        self.assert_error(mutated(edit), "DUPLICATE_TICK", index=2)

    def test_ticks_must_strictly_increase(self):
        def edit(p):
            p["tempoPoints"] = [
                {"tick": 0, "microsPerQuarter": 500000, "mode": "hold"},
                {"tick": 480, "microsPerQuarter": 500000, "mode": "hold"},
                {"tick": 240, "microsPerQuarter": 400000, "mode": "hold"},
            ]
        self.assert_error(mutated(edit), "TICKS_NOT_INCREASING", index=2)

    def test_illegal_mode(self):
        self.assert_error(
            mutated(lambda p: p["tempoPoints"][0].__setitem__("mode", "glide")),
            "ILLEGAL_MODE", index=0, path="tempoPoints[0].mode",
        )

    def test_illegal_mode_on_last_point_is_still_rejected(self):
        def edit(p):
            p["tempoPoints"].append(
                {"tick": 480, "microsPerQuarter": 400000, "mode": "glide"})
        self.assert_error(mutated(edit), "ILLEGAL_MODE", index=1)

    def test_non_positive_tempo(self):
        for bad in (0, -1):
            self.assert_error(
                mutated(lambda p, b=bad: p["tempoPoints"][0].__setitem__(
                    "microsPerQuarter", b)),
                "NON_POSITIVE_TEMPO", index=0,
            )

    def test_cue_out_of_range(self):
        def edit(p):
            p["cues"] = [{"id": "ok", "tick": 0}, {"id": "bad", "tick": -1}]
        self.assert_error(mutated(edit), "CUE_OUT_OF_RANGE", index=1,
                          path="cues[1].tick")

    def test_duplicate_cue_id(self):
        def edit(p):
            p["cues"] = [{"id": "x", "tick": 0}, {"id": "x", "tick": 10}]
        self.assert_error(mutated(edit), "DUPLICATE_CUE_ID", index=1)

    def test_tempo_point_count_bounds(self):
        self.assert_error(mutated(lambda p: p.__setitem__("tempoPoints", [])),
                          "TEMPO_POINT_COUNT_OUT_OF_RANGE")
        too_many = [
            {"tick": i, "microsPerQuarter": 500000, "mode": "hold"}
            for i in range(501)
        ]
        self.assert_error(mutated(lambda p: p.__setitem__("tempoPoints", too_many)),
                          "TEMPO_POINT_COUNT_OUT_OF_RANGE")

    def test_cue_count_bounds(self):
        self.assert_error(mutated(lambda p: p.__setitem__("cues", [])),
                          "CUE_COUNT_OUT_OF_RANGE")
        too_many = [{"id": i, "tick": i} for i in range(2001)]
        self.assert_error(mutated(lambda p: p.__setitem__("cues", too_many)),
                          "CUE_COUNT_OUT_OF_RANGE")

    def test_top_level_fields(self):
        self.assert_error(mutated(lambda p: p.pop("ticksPerQuarter")),
                          "MISSING_FIELD", status=400)
        self.assert_error(mutated(lambda p: p.__setitem__("ticksPerQuarter", 0)),
                          "INVALID_FIELD_VALUE")
        self.assert_error(mutated(lambda p: p.__setitem__("sampleRate", -48000)),
                          "INVALID_FIELD_VALUE")
        self.assert_error(mutated(lambda p: p.__setitem__("sampleRate", "48000")),
                          "INVALID_FIELD_TYPE", status=400)

    def test_field_types(self):
        # JSON booleans and floats are not valid ticks.
        self.assert_error(
            mutated(lambda p: p["tempoPoints"][0].__setitem__("tick", True)),
            "INVALID_FIELD_TYPE", status=400)
        self.assert_error(
            mutated(lambda p: p["tempoPoints"][0].__setitem__("tick", 0.5)),
            "INVALID_FIELD_TYPE", status=400)
        self.assert_error(
            mutated(lambda p: p["cues"][0].__setitem__("tick", 1.5)),
            "INVALID_FIELD_TYPE", status=400)

    def test_non_object_payload(self):
        self.assert_error([], "INVALID_PAYLOAD", status=400, path="$")

    def test_maximum_sizes_are_accepted(self):
        payload = mutated(lambda p: None)
        payload["tempoPoints"] = [
            {"tick": i, "microsPerQuarter": 500000, "mode": "hold"}
            for i in range(500)
        ]
        payload["cues"] = [{"id": i, "tick": i} for i in range(2000)]
        result = project(payload)
        self.assertEqual(len(result), 2000)


if __name__ == "__main__":
    unittest.main()

"""Request validation.

Every domain rule violation raises an :class:`ApiError` carrying a stable
error code and the position of the offending element. Validation is all or
nothing: the first failure aborts the request, so an error response never
carries partial projection results.
"""
from .errors import ApiError

HOLD = "hold"
RAMP = "ramp"
MODES = (HOLD, RAMP)

MIN_TEMPO_POINTS = 1
MAX_TEMPO_POINTS = 500
MIN_CUES = 1
MAX_CUES = 2000


def _is_int(value):
    # bool is a subclass of int; JSON true/false is never a valid tick.
    return isinstance(value, int) and not isinstance(value, bool)


def _pos(path, index=None):
    position = {"path": path}
    if index is not None:
        position["index"] = index
    return position


def _missing(path, index=None):
    return ApiError("MISSING_FIELD", f"{path} is required", _pos(path, index), status=400)


def _type_error(path, expectation, index=None):
    return ApiError("INVALID_FIELD_TYPE", f"{path} must be {expectation}", _pos(path, index), status=400)


def _positive_int(payload, field):
    if field not in payload:
        raise _missing(field)
    value = payload[field]
    if not _is_int(value):
        raise _type_error(field, "an integer")
    if value <= 0:
        raise ApiError(
            "INVALID_FIELD_VALUE",
            f"{field} must be a positive integer, got {value}",
            _pos(field),
        )
    return value


def _tempo_points(payload):
    if "tempoPoints" not in payload:
        raise _missing("tempoPoints")
    points = payload["tempoPoints"]
    if not isinstance(points, list):
        raise _type_error("tempoPoints", "an array")
    if not MIN_TEMPO_POINTS <= len(points) <= MAX_TEMPO_POINTS:
        raise ApiError(
            "TEMPO_POINT_COUNT_OUT_OF_RANGE",
            f"tempoPoints must contain between {MIN_TEMPO_POINTS} and "
            f"{MAX_TEMPO_POINTS} points, got {len(points)}",
            _pos("tempoPoints"),
        )

    normalized = []
    for i, point in enumerate(points):
        base = f"tempoPoints[{i}]"
        if not isinstance(point, dict):
            raise _type_error(base, "an object", i)

        if "tick" not in point:
            raise _missing(f"{base}.tick", i)
        tick = point["tick"]
        if not _is_int(tick):
            raise _type_error(f"{base}.tick", "an integer", i)
        if tick < 0:
            raise ApiError(
                "INVALID_FIELD_VALUE",
                f"{base}.tick must be non-negative, got {tick}",
                _pos(f"{base}.tick", i),
            )

        if "microsPerQuarter" not in point:
            raise _missing(f"{base}.microsPerQuarter", i)
        mpq = point["microsPerQuarter"]
        if not _is_int(mpq):
            raise _type_error(f"{base}.microsPerQuarter", "an integer", i)
        if mpq <= 0:
            raise ApiError(
                "NON_POSITIVE_TEMPO",
                f"{base}.microsPerQuarter must be a positive integer, got {mpq}",
                _pos(f"{base}.microsPerQuarter", i),
            )

        if "mode" not in point:
            raise _missing(f"{base}.mode", i)
        mode = point["mode"]
        if not isinstance(mode, str):
            raise _type_error(f"{base}.mode", "a string", i)
        if mode not in MODES:
            raise ApiError(
                "ILLEGAL_MODE",
                f"{base}.mode must be one of {list(MODES)}, got {mode!r}",
                _pos(f"{base}.mode", i),
            )

        normalized.append({"tick": tick, "microsPerQuarter": mpq, "mode": mode})

    first_tick = normalized[0]["tick"]
    if first_tick != 0:
        raise ApiError(
            "TEMPO_MAP_GAP",
            f"tempo map must start at tick 0, first point is at tick {first_tick}",
            _pos("tempoPoints[0].tick", 0),
        )
    for i in range(1, len(normalized)):
        prev = normalized[i - 1]["tick"]
        cur = normalized[i]["tick"]
        if cur == prev:
            raise ApiError(
                "DUPLICATE_TICK",
                f"tempoPoints[{i}].tick {cur} duplicates tempoPoints[{i - 1}].tick",
                _pos(f"tempoPoints[{i}].tick", i),
            )
        if cur < prev:
            raise ApiError(
                "TICKS_NOT_INCREASING",
                f"tempoPoints[{i}].tick {cur} is below tempoPoints[{i - 1}].tick "
                f"{prev}; ticks must strictly increase",
                _pos(f"tempoPoints[{i}].tick", i),
            )
    return normalized


def _cues(payload):
    if "cues" not in payload:
        raise _missing("cues")
    cues = payload["cues"]
    if not isinstance(cues, list):
        raise _type_error("cues", "an array")
    if not MIN_CUES <= len(cues) <= MAX_CUES:
        raise ApiError(
            "CUE_COUNT_OUT_OF_RANGE",
            f"cues must contain between {MIN_CUES} and {MAX_CUES} cues, got {len(cues)}",
            _pos("cues"),
        )

    seen_ids = set()
    normalized = []
    for i, cue in enumerate(cues):
        base = f"cues[{i}]"
        if not isinstance(cue, dict):
            raise _type_error(base, "an object", i)

        if "id" not in cue:
            raise _missing(f"{base}.id", i)
        cid = cue["id"]
        valid_id = (isinstance(cid, str) and cid != "") or _is_int(cid)
        if not valid_id:
            raise ApiError(
                "INVALID_CUE_ID",
                f"{base}.id must be a non-empty string or an integer",
                _pos(f"{base}.id", i),
                status=400,
            )
        key = (type(cid).__name__, cid)
        if key in seen_ids:
            raise ApiError(
                "DUPLICATE_CUE_ID",
                f"{base}.id {cid!r} is already used by an earlier cue",
                _pos(f"{base}.id", i),
            )
        seen_ids.add(key)

        if "tick" not in cue:
            raise _missing(f"{base}.tick", i)
        tick = cue["tick"]
        if not _is_int(tick):
            raise _type_error(f"{base}.tick", "an integer", i)
        if tick < 0:
            raise ApiError(
                "CUE_OUT_OF_RANGE",
                f"{base}.tick {tick} is negative; cues must sit on non-negative ticks",
                _pos(f"{base}.tick", i),
            )

        normalized.append({"id": cid, "tick": tick})
    return normalized


def validate_request(payload):
    """Validate the raw payload and return normalized data.

    Raises ApiError on the first problem found; nothing is returned
    partially validated.
    """
    if not isinstance(payload, dict):
        raise ApiError(
            "INVALID_PAYLOAD",
            "request body must be a JSON object",
            _pos("$"),
            status=400,
        )
    return {
        "ticksPerQuarter": _positive_int(payload, "ticksPerQuarter"),
        "sampleRate": _positive_int(payload, "sampleRate"),
        "tempoPoints": _tempo_points(payload),
        "cues": _cues(payload),
    }

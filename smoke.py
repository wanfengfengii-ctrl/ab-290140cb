#!/usr/bin/env python3
"""API smoke test: hold segments, ramp segments, rounding and error codes.

Targets APP_URL (default http://127.0.0.1:8080). Exits 0 when every check
passes, 1 otherwise.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("APP_URL", "http://127.0.0.1:8080").rstrip("/")

_failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
    else:
        _failures.append(name)
        print(f"  FAIL {name} {detail}")


def wait_ready(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def post(payload):
    req = urllib.request.Request(
        BASE + "/api/timelines/project",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def expect_projection(name, payload, want_ns, want_frames):
    status, body = post(payload)
    ok = status == 200 and "projections" in body
    check(f"{name}: HTTP 200 with projections", ok, f"got {status} {body}")
    if not ok:
        return
    got_ns = [p["nanoseconds"] for p in body["projections"]]
    got_frames = [p["frame"] for p in body["projections"]]
    check(f"{name}: nanoseconds", got_ns == want_ns, f"got {got_ns} want {want_ns}")
    check(f"{name}: frames", got_frames == want_frames,
          f"got {got_frames} want {want_frames}")


def expect_error(name, payload, want_code, want_index=None):
    status, body = post(payload)
    check(f"{name}: HTTP 422", status == 422, f"got {status}")
    check(f"{name}: no partial projections", "projections" not in body)
    err = body.get("error", {})
    check(f"{name}: code {want_code}", err.get("code") == want_code,
          f"got {err.get('code')}")
    if want_index is not None:
        check(f"{name}: position index {want_index}",
              err.get("position", {}).get("index") == want_index,
              f"got {err.get('position')}")


def main():
    print(f"[smoke] target {BASE}")
    if not wait_ready():
        print("[smoke] FAIL service did not become healthy in time")
        return 1
    print("[smoke] service healthy")

    print("[smoke] hold segments")
    expect_projection(
        "hold",
        {
            "ticksPerQuarter": 480,
            "sampleRate": 48000,
            "tempoPoints": [
                {"tick": 0, "microsPerQuarter": 500000, "mode": "hold"},
                {"tick": 960, "microsPerQuarter": 250000, "mode": "hold"},
            ],
            "cues": [
                {"id": "a", "tick": 0},
                {"id": "b", "tick": 480},
                {"id": "c", "tick": 960},
                {"id": "d", "tick": 1440},
            ],
        },
        [0, 500_000_000, 1_000_000_000, 1_250_000_000],
        [0, 24000, 48000, 60000],
    )

    print("[smoke] ramp segments")
    expect_projection(
        "ramp",
        {
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
        },
        [437_500_000, 750_000_000, 1_000_000_000],
        [21000, 36000, 48000],
    )

    print("[smoke] half-even rounding from unrounded cumulative time")
    expect_projection(
        "half-even",
        {
            "ticksPerQuarter": 2000,
            "sampleRate": 1_000_000_000,
            "tempoPoints": [{"tick": 0, "microsPerQuarter": 1, "mode": "hold"}],
            "cues": [{"id": str(t), "tick": t} for t in (1, 2, 3, 5)],
        },
        [0, 1, 2, 2],  # 0.5ns -> 0, 1.5ns -> 2, 2.5ns -> 2 (ties to even)
        [0, 1, 2, 2],
    )

    print("[smoke] same tick projects identically, order preserved")
    status, body = post({
        "ticksPerQuarter": 480,
        "sampleRate": 48000,
        "tempoPoints": [{"tick": 0, "microsPerQuarter": 500000, "mode": "hold"}],
        "cues": [
            {"id": "z", "tick": 960},
            {"id": "x", "tick": 480},
            {"id": "y", "tick": 480},
        ],
    })
    projs = body.get("projections", [])
    check("same-tick: order", [p.get("id") for p in projs] == ["z", "x", "y"])
    check(
        "same-tick: identical projection",
        len(projs) == 3
        and (projs[1]["nanoseconds"], projs[1]["frame"])
        == (projs[2]["nanoseconds"], projs[2]["frame"]),
    )

    print("[smoke] error codes")
    base = {
        "ticksPerQuarter": 480,
        "sampleRate": 48000,
        "tempoPoints": [{"tick": 0, "microsPerQuarter": 500000, "mode": "hold"}],
        "cues": [{"id": "a", "tick": 0}],
    }

    def variant(**over):
        payload = json.loads(json.dumps(base))
        payload.update(over)
        return payload

    expect_error("gap", variant(tempoPoints=[
        {"tick": 5, "microsPerQuarter": 500000, "mode": "hold"}]),
        "TEMPO_MAP_GAP", 0)
    expect_error("duplicate tick", variant(tempoPoints=[
        {"tick": 0, "microsPerQuarter": 500000, "mode": "hold"},
        {"tick": 480, "microsPerQuarter": 500000, "mode": "hold"},
        {"tick": 480, "microsPerQuarter": 400000, "mode": "hold"}]),
        "DUPLICATE_TICK", 2)
    expect_error("illegal mode", variant(tempoPoints=[
        {"tick": 0, "microsPerQuarter": 500000, "mode": "swing"}]),
        "ILLEGAL_MODE", 0)
    expect_error("non-positive tempo", variant(tempoPoints=[
        {"tick": 0, "microsPerQuarter": 0, "mode": "hold"}]),
        "NON_POSITIVE_TEMPO", 0)
    expect_error("cue out of range", variant(cues=[{"id": "a", "tick": -3}]),
                 "CUE_OUT_OF_RANGE", 0)
    expect_error("duplicate cue id", variant(cues=[
        {"id": "a", "tick": 0}, {"id": "a", "tick": 10}]),
        "DUPLICATE_CUE_ID", 1)

    if _failures:
        print(f"[smoke] {len(_failures)} check(s) failed: {', '.join(_failures)}")
        return 1
    print("[smoke] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Foley bed: a whoosh per cut, one low impact on the twist, quiet room tone.

All synthesised here — no third-party audio, no licence questions.

Run: python scripts/foley.py --shotlist shotlist.json --out public/foley
"""
import argparse
import json
import os
import wave

import numpy as np

RATE = 24000


def write(path, x, rate=RATE):
    x = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((x * 32767.0).astype(np.int16).tobytes())


def lowpass(x, k=0.15):
    y = np.zeros_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += k * (v - acc)
        y[i] = acc
    return y


def whoosh(seed=1, dur=0.38):
    n = int(dur * RATE)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n).astype(np.float32)
    # sweep the filter by mixing filtered copies with a moving weight
    soft = lowpass(noise, 0.06)
    hard = lowpass(noise, 0.35)
    w = np.linspace(0, 1, n) ** 1.6
    body = soft * (1 - w) + hard * w
    env = np.sin(np.linspace(0, np.pi, n)) ** 1.4
    return (body * env * 0.42).astype(np.float32)


def boom(seed=7, dur=0.85):
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    rng = np.random.default_rng(seed)
    sweep = np.sin(2 * np.pi * (62 * np.exp(-3.2 * t) + 34) * t)
    env = np.exp(-4.6 * t)
    noise = lowpass(rng.standard_normal(n).astype(np.float32), 0.03)
    return ((sweep * 0.85 + noise * 0.5) * env * 0.5).astype(np.float32)


def roomtone(seed=3, dur=12.0, level=0.012):
    n = int(dur * RATE)
    rng = np.random.default_rng(seed)
    x = lowpass(rng.standard_normal(n).astype(np.float32), 0.02)
    x = x / (np.max(np.abs(x)) + 1e-9) * level
    # fade the loop ends so the join is inaudible
    f = int(0.25 * RATE)
    ramp = np.linspace(0, 1, f, dtype=np.float32)
    x[:f] *= ramp
    x[-f:] *= ramp[::-1]
    return x.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shotlist", default="shotlist.json")
    ap.add_argument("--out", default="public/foley")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    write(os.path.join(args.out, "whoosh.wav"), whoosh())
    write(os.path.join(args.out, "boom.wav"), boom())
    write(os.path.join(args.out, "room.wav"), roomtone())

    with open(args.shotlist) as fh:
        shots = json.load(fh)["shots"]
    # the twist beat: the shot that says the mass is in the core
    twist = next((s["id"] for s in shots if s["id"].startswith("07")), shots[-2]["id"])
    with open(os.path.join(args.out, "cues.json"), "w") as fh:
        json.dump({"whoosh": "foley/whoosh.wav", "boom": "foley/boom.wav",
                   "room": "foley/room.wav", "twistShot": twist,
                   "cuts": [s["start"] for s in shots[1:]]}, fh, indent=2)
    print(f"FOLEY wrote {args.out} (whoosh, boom, room tone), twist on {twist}")


if __name__ == "__main__":
    main()

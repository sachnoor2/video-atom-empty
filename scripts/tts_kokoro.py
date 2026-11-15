"""Kokoro-82M narration: one WAV per scene, and a manifest built from measured audio.

Scene lengths are derived from the audio, never typed:
    frames = round((seconds + pad) * fps)

Run: python scripts/tts_kokoro.py --model kokoro-v1.0.onnx --voices voices-v1.0.bin
"""
import argparse
import json
import os
import wave

import numpy as np
from kokoro_onnx import Kokoro


def write_wav(path, samples, rate):
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return len(pcm) / float(rate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--narration", default="narration.json")
    ap.add_argument("--model", default="kokoro-v1.0.onnx")
    ap.add_argument("--voices", default="voices-v1.0.bin")
    ap.add_argument("--outdir", default="public/audio")
    ap.add_argument("--manifest", default="src/manifest.json")
    args = ap.parse_args()

    with open(args.narration) as fh:
        spec = json.load(fh)
    fps = spec.get("fps", 30)
    pad = spec.get("pad", 0.65)
    min_seconds = spec.get("minSeconds", 2.6)
    voice = spec.get("voice", "am_michael")
    lang = spec.get("lang", "en-us")
    speed = spec.get("speed", 1.0)

    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(os.path.dirname(args.manifest) or ".", exist_ok=True)
    kokoro = Kokoro(args.model, args.voices)

    scenes = []
    total = 0
    for s in spec["scenes"]:
        text = s["text"].strip()
        v = s.get("voice", voice)
        lg = s.get("lang", lang)
        sp = s.get("speed", speed)
        samples, rate = kokoro.create(text, voice=v, speed=sp, lang=lg)
        path = os.path.join(args.outdir, f"{s['id']}.wav")
        seconds = write_wav(path, samples, rate)
        seconds = max(seconds, min_seconds)
        frames = int(round((seconds + pad) * fps))
        scenes.append({"id": s["id"], "text": text, "seconds": round(seconds, 3),
                       "frames": frames, "audio": f"audio/{s['id']}.wav"})
        total += frames
        print(f"TTS {s['id']} {seconds:.2f}s -> {frames} frames", flush=True)

    manifest = {"fps": fps, "width": 720, "height": 1280, "pad": pad,
                "totalFrames": total, "durationSeconds": round(total / fps, 3),
                "scenes": scenes}
    with open(args.manifest, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"MANIFEST {args.manifest} totalFrames={total} {total / fps:.2f}s")


if __name__ == "__main__":
    main()
